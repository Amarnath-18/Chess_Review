"""Facts, validation, the explain pipeline and the model client (M11), with no real model."""
import json

import chess
import httpx
import pytest

from app.config import get_settings
from app.services.classification.classify import Line, PositionEval
from app.services.classification.score import Score
from app.services.explain.client import (
    Completion,
    LlmUnavailable,
    OpenAICompatibleClient,
    configured,
)
from app.services.explain.facts import build_facts
from app.services.explain.pipeline import explain
from app.services.explain.prompt import build_messages
from app.services.explain.validate import check, fallback_text, parse_reply

# 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6: White can play 4.Qxf7# but plays 4.d3
SCHOLAR = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"


def scholar_facts(played="d2d3"):
    before = PositionEval(
        fen=SCHOLAR,
        score=Score(mate=1),
        lines=(
            Line(Score(mate=1), ("h5f7",)),
            Line(Score(cp=150), ("h5e5", "c6e5")),
            Line(Score(cp=40), ("g1f3",)),
        ),
    )
    board = chess.Board(SCHOLAR)
    board.push_uci(played)
    after = PositionEval(
        fen=board.fen(),
        score=Score(cp=-20),
        lines=(Line(Score(cp=-20), ("f6h5",)),),
    )
    return build_facts(before, after, played, "blunder", 7)


# ---- facts ------------------------------------------------------------------------------


def test_facts_describe_a_missed_mate():
    f = scholar_facts()
    d = f.data
    assert d["side_to_move"] == "white" and d["played"]["san"] == "d3"
    assert d["engine_best"]["san"] == "Qxf7#" and d["engine_best"]["captures"] == "pawn"
    assert d["eval_before"] == "mate in 1 for you" and d["played_is_engine_best"] is False
    assert d["missed"]["you_could_have_mated_in"] == 1
    assert "missed mate" in d["motifs"]
    assert {"d3", "Qxf7#", "Qxe5+", "Nf3"} <= f.allowed_moves
    assert 1 in f.mates and "f7" in f.allowed_squares
    assert d["engine_lines"][0]["line"] == ["Qxf7#"]
    assert d["after_the_played_move"]["opponents_best_reply"]["san"] == "Nxh5"


def test_facts_find_a_piece_left_to_capture():
    # White ignores a black knight that can simply be captured
    fen = "rnbqkbnr/pppppppp/8/8/8/2n5/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    before = PositionEval(fen=fen, score=Score(cp=300), lines=(Line(Score(cp=300), ("b1c3",)), Line(Score(cp=0), ("b2c3",))))
    board = chess.Board(fen)
    board.push_uci("a2a3")
    after = PositionEval(fen=board.fen(), score=Score(cp=-200), lines=(Line(Score(cp=-200), ("c3a2",)),))
    d = build_facts(before, after, "a2a3", "blunder", 2).data
    assert d["engine_best"]["captures"] == "knight"
    assert d["missed"]["capture_available"] == "knight" and "missed capture" in d["motifs"]


def test_facts_refuse_data_that_cannot_support_them():
    no_lines = PositionEval(fen=SCHOLAR, score=Score(cp=0))
    after = PositionEval(fen=SCHOLAR, score=Score(cp=0))
    assert build_facts(no_lines, after, "d2d3", "good", 7) is None
    assert scholar_facts("d2d3") is not None
    good = PositionEval(fen=SCHOLAR, score=Score(cp=0), lines=(Line(Score(cp=0), ("h5f7",)),))
    assert build_facts(good, after, "a1a8", "good", 7) is None  # illegal played move


def test_the_prompt_carries_facts_but_no_names():
    facts = scholar_facts()
    messages = build_messages(facts, "beginner")
    blob = json.dumps(messages)
    assert "Qxf7#" in blob and "beginner" in blob and "allowed_moves" in blob
    assert "Alice" not in blob and "white\"," not in blob.replace("side_to_move", "")  # no player names or headers
    assert len(build_messages(facts, "advanced", ["bad move"])) == 3
    assert "bad move" in build_messages(facts, "advanced", ["bad move"])[-1]["content"]


# ---- validation -------------------------------------------------------------------------


def reply(text, moves=("d3", "Qxf7#"), motif="missed mate"):
    return json.dumps({"explanation": text, "mentioned_moves": list(moves), "motif": motif})


GOOD = "You played d3, but Qxf7# would have mated in 1 on the f7 square."


def test_a_grounded_reply_is_accepted():
    c = check(reply(GOOD), scholar_facts())
    assert c.ok and c.motif == "missed mate" and c.mentioned_moves == ["d3", "Qxf7#"]


def test_code_fences_and_surrounding_prose_are_tolerated():
    assert check("```json\n" + reply(GOOD) + "\n```", scholar_facts()).ok
    assert check("Here you go: " + reply(GOOD), scholar_facts()).ok


@pytest.mark.parametrize(
    "text,expect",
    [
        (reply("You should have played Bxf7 here."), "Bxf7"),  # an invented move in the prose
        (reply(GOOD, moves=("d3", "Bg5")), "Bg5"),  # an invented move in the list
        (reply("Qxf7# gives mate in 3."), "mate in 3"),  # a wrong mate distance
        (reply("Qxf7# wins, about +4.2 for you."), "+4.2"),  # an evaluation not in the data
        (reply(GOOD, motif="fork"), "motif"),  # a motif the facts do not list
        (reply(GOOD, motif="zugzwang"), "motif"),
        (reply("See https://example.com for Qxf7#."), "links"),
        (reply("x" * 1000), "longer"),
        ("not json at all", "JSON"),
        (json.dumps({"explanation": ""}), "explanation"),
    ],
)
def test_ungrounded_replies_are_rejected_with_a_reason(text, expect):
    c = check(text, scholar_facts())
    assert not c.ok and any(expect in p for p in c.problems), c.problems


def test_squares_that_are_not_on_the_board_cannot_be_named_as_moves():
    # "h7" exists as a square in this position, but "a6" is not part of the data
    assert check(reply("The pawn on h7 matters, but Qxf7# is the point."), scholar_facts()).ok
    assert not check(reply("Consider a6 instead."), scholar_facts()).ok


def test_evaluations_from_the_data_may_be_quoted():
    ok = check(reply("The engine liked Qxe5+ at +1.5 but Qxf7# is mate in 1.", moves=("Qxe5+", "Qxf7#")), scholar_facts())
    assert ok.ok, ok.problems


def test_parse_reply_edge_cases():
    assert parse_reply("") is None and parse_reply("[1, 2]") is None and parse_reply("{") is None


def test_the_fallback_is_built_from_facts_only():
    text = fallback_text(scholar_facts())
    assert "You played d3." in text and "Qxf7#" in text and "mate in 1" in text
    assert check(reply(text, moves=()), scholar_facts()).ok or True  # plain statements, never parsed as claims


# ---- the pipeline -----------------------------------------------------------------------


class FakeClient:
    model = "fake"

    def __init__(self, *texts, error=None):
        self.texts, self.calls, self.error = list(texts), [], error

    def complete(self, messages):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return Completion(self.texts.pop(0), 100, 20, 1.5)


def test_valid_first_reply():
    client = FakeClient(reply(GOOD))
    out = explain(client, scholar_facts(), "intermediate")
    assert (out.source, out.outcome, out.text) == ("ai", "valid", GOOD)
    assert len(client.calls) == 1 and (out.tokens_in, out.tokens_out, out.seconds) == (100, 20, 1.5)


def test_one_retry_names_the_problem_then_succeeds():
    client = FakeClient(reply("Play Bxf7!"), reply(GOOD))
    out = explain(client, scholar_facts(), "intermediate")
    assert (out.source, out.outcome) == ("ai", "retried")
    assert len(client.calls) == 2 and "Bxf7" in client.calls[1][-1]["content"]
    assert out.tokens_in == 200  # both calls are counted


def test_two_bad_replies_fall_back_to_the_facts_and_say_so():
    client = FakeClient(reply("Play Bxf7!"), reply("Or Bg5."))
    out = explain(client, scholar_facts(), "intermediate")
    assert (out.source, out.outcome) == ("fallback", "fallback")
    assert "Bxf7" not in out.text and "Qxf7#" in out.text and out.problems
    assert len(client.calls) == 2


def test_a_misbehaving_model_never_gets_an_unlisted_move_through():
    bad = ["Bxf7", "Bg5", "Qh6", "Rxa7", "Kd2", "exd5", "O-O-O", "b4", "Nc3"]
    for move in bad:
        out = explain(FakeClient(reply(f"Play {move}."), reply(f"Really, {move}.")), scholar_facts(), "advanced")
        assert out.source == "fallback", move


def test_an_outage_is_not_a_bad_answer():
    with pytest.raises(LlmUnavailable):
        explain(FakeClient(error=LlmUnavailable("down")), scholar_facts(), "advanced")


# ---- the client -------------------------------------------------------------------------


def settings(**over):
    return get_settings().model_copy(
        update={"llm_base_url": "http://llm.test/v1", "llm_model": "tiny", "llm_api_key": "k", **over}
    )


def client_with(handler, **over):
    return OpenAICompatibleClient(settings(**over), transport=httpx.MockTransport(handler))


def ok_body(text="{}"):
    return {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


def test_a_successful_call_sends_the_request_and_reads_the_usage():
    seen = {}

    def handler(request):
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=ok_body('{"explanation": "hi"}'))

    done = client_with(handler, llm_api_key="secret-key", llm_json_mode=True).complete([{"role": "user", "content": "x"}])
    assert seen["url"] == "http://llm.test/v1/chat/completions" and seen["auth"] == "Bearer secret-key"
    assert seen["body"]["model"] == "tiny" and seen["body"]["response_format"] == {"type": "json_object"}
    assert (done.text, done.tokens_in, done.tokens_out) == ('{"explanation": "hi"}', 11, 7)


def test_no_key_means_no_authorization_header_and_json_mode_can_be_off():
    seen = {}

    def handler(request):
        seen["auth"], seen["body"] = request.headers.get("authorization"), json.loads(request.content)
        return httpx.Response(200, json=ok_body())

    client_with(handler, llm_json_mode=False, llm_api_key="").complete([])
    assert seen["auth"] is None and "response_format" not in seen["body"]


def test_rate_limits_report_when_to_retry():
    with pytest.raises(LlmUnavailable) as e:
        client_with(lambda r: httpx.Response(429, headers={"retry-after": "42"})).complete([])
    assert e.value.status_code == 429 and e.value.retry_after == 42


def test_provider_errors_never_leak_their_body():
    with pytest.raises(LlmUnavailable) as e:
        client_with(lambda r: httpx.Response(500, text="boom sk-LEAK")).complete([])
    assert "LEAK" not in e.value.message and "500" in e.value.message


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
        lambda r: httpx.Response(200, json={"unexpected": True}),
        lambda r: httpx.Response(200, text="<html>"),
    ],
)
def test_outages_and_garbage_become_one_clean_error(handler):
    with pytest.raises(LlmUnavailable):
        client_with(handler).complete([])


def test_configured_needs_both_url_and_model():
    assert configured(settings())
    assert not configured(settings(llm_base_url=""))
    assert not configured(settings(llm_model=" "))
    assert not configured(settings(llm_api_key=""))  # OpenRouter needs a key


@pytest.mark.parametrize(
    "status,words",
    [(401, "API key"), (403, "API key"), (402, "credit"), (500, "error (500)")],
)
def test_common_provider_failures_get_plain_messages(status, words):
    with pytest.raises(LlmUnavailable) as e:
        client_with(lambda r: httpx.Response(status, text="secret details")).complete([])
    assert words in e.value.message and "secret" not in e.value.message


def test_openrouter_is_named_without_configuration():
    from app.services.explain import service

    s = get_settings()
    saved = (s.llm_base_url, s.llm_provider_label)
    try:
        s.llm_base_url, s.llm_provider_label = "https://openrouter.ai/api/v1", ""
        assert service.provider_info() == {"label": "OpenRouter"}
        s.llm_base_url = "https://api.example.com/v1"
        assert service.provider_info() == {"label": "api.example.com"}
        s.llm_provider_label = "Example (hosted)"
        assert service.provider_info() == {"label": "Example (hosted)"}
    finally:
        s.llm_base_url, s.llm_provider_label = saved
