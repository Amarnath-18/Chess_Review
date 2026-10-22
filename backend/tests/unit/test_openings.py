import chess

from app.services.openings import book_run, lookup


def _fens(*sans: str) -> list[str]:
    board = chess.Board()
    out = []
    for san in sans:
        board.push_san(san)
        out.append(board.fen())
    return out


def test_known_position_is_named():
    board = chess.Board()
    for san in ("e4", "e5", "Nf3", "Nc6", "Bb5"):
        board.push_san(san)
    eco, name = lookup(board)
    assert eco == "C60" and name.startswith("Ruy Lopez")


def test_transposition_is_recognised():
    a = chess.Board()
    for san in ("e4", "c5", "Nf3", "d6"):
        a.push_san(san)
    b = chess.Board()
    for san in ("Nf3", "d6", "e4", "c5"):
        b.push_san(san)
    assert lookup(a) == lookup(b) and lookup(a) is not None


def test_book_ends_at_novelty_and_does_not_return():
    start = chess.STARTING_FEN
    run = book_run(start, _fens("e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "h6", "Bb3", "h5"))
    assert all(h is not None for h in run[:7])  # e4 ... Ba4: unnamed steps are still theory
    assert run[5][1].startswith("Ruy Lopez: Morphy")
    assert run[7] is None  # 4...h6 is out of book
    assert all(h is None for h in run[7:])


def test_games_from_a_custom_position_have_no_book():
    custom = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"
    board = chess.Board(custom)
    board.push_san("e5")
    assert book_run(custom, [board.fen()]) == [None]
