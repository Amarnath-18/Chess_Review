import { useEffect, useState } from "react";
import { useGameNotes } from "../api/hooks";
import type { GameDetail } from "../api/types";

const MAX_TAGS = 20;
const field =
  "w-full rounded border border-slate-300 bg-white p-2 text-sm dark:border-slate-600 dark:bg-slate-950";
const smallBtn =
  "min-h-11 rounded border border-slate-300 px-3 text-sm font-medium hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800";

function Err({ error }: { error: unknown }) {
  return error ? (
    <p role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">
      {(error as Error).message}
    </p>
  ) : null;
}

/** An editable text with its own Save button, so nothing is sent while you are still typing. */
function NoteEditor({
  label,
  hint,
  saved,
  max,
  onSave,
  busy,
  error,
  testId,
}: {
  label: string;
  hint?: string;
  saved: string;
  max: number;
  onSave: (text: string) => void;
  busy: boolean;
  error: unknown;
  testId: string;
}) {
  const [text, setText] = useState(saved);
  useEffect(() => setText(saved), [saved]); // another move, or the server's version
  const dirty = text.trim() !== saved.trim();
  return (
    <div>
      <label className="block text-sm">
        <span className="mb-1 block font-medium">{label}</span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          maxLength={max}
          className={field}
          data-testid={testId}
        />
      </label>
      <div className="mt-1 flex items-center justify-between gap-2">
        <span className="text-xs text-slate-600 dark:text-slate-400">{hint ?? `${text.length}/${max}`}</span>
        <button type="button" disabled={!dirty || busy} onClick={() => onSave(text)} className={smallBtn}>
          {busy ? "Saving…" : dirty ? "Save" : "Saved"}
        </button>
      </div>
      <Err error={error} />
    </div>
  );
}

/** Your own favourite mark, tags and notes for this game and for the move on the board. */
export function GameNotes({ game, ply, moveLabel }: { game: GameDetail; ply: number; moveLabel: (ply: number) => string }) {
  const { update, moveNote } = useGameNotes(game.id);
  const [tagText, setTagText] = useState("");
  const tags = game.tags ?? [];
  const favorite = !!game.favorite;
  const addTag = () => {
    const t = tagText.trim();
    if (!t) return;
    update.mutate({ tags: [...tags, t] }, { onSuccess: () => setTagText("") });
  };

  return (
    <section aria-label="Your notes" className="space-y-4" data-testid="game-notes">
      <button
        type="button"
        aria-pressed={favorite}
        disabled={update.isPending}
        onClick={() => update.mutate({ favorite: !favorite })}
        className={`${smallBtn} inline-flex items-center gap-2`}
      >
        <span aria-hidden="true" className={favorite ? "text-amber-500" : ""}>
          {favorite ? "★" : "☆"}
        </span>
        {favorite ? "Favourite" : "Mark as favourite"}
      </button>

      <div>
        <h3 className="mb-1 text-sm font-medium">Tags</h3>
        {tags.length > 0 && (
          <ul className="mb-2 flex flex-wrap gap-1" aria-label="Tags on this game">
            {tags.map((t) => (
              <li
                key={t}
                className="inline-flex items-center gap-1 rounded-full bg-slate-200 py-0.5 pl-2 pr-1 text-xs dark:bg-slate-700"
              >
                {t}
                <button
                  type="button"
                  aria-label={`Remove tag ${t}`}
                  onClick={() => update.mutate({ tags: tags.filter((x) => x !== t) })}
                  className="inline-flex h-6 w-6 items-center justify-center rounded-full hover:bg-slate-300 dark:hover:bg-slate-600"
                >
                  <span aria-hidden="true">×</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            addTag();
          }}
        >
          <label className="min-w-0 flex-1 text-sm">
            <span className="sr-only">New tag</span>
            <input
              value={tagText}
              onChange={(e) => setTagText(e.target.value)}
              maxLength={30}
              placeholder={tags.length >= MAX_TAGS ? "Tag limit reached" : "Add a tag, e.g. endgame"}
              disabled={tags.length >= MAX_TAGS}
              className={field}
            />
          </label>
          <button type="submit" disabled={!tagText.trim() || update.isPending} className={smallBtn}>
            Add tag
          </button>
        </form>
      </div>

      <NoteEditor
        label="Note on this game"
        saved={game.note ?? ""}
        max={5000}
        busy={update.isPending}
        error={update.error}
        onSave={(text) => update.mutate({ note: text })}
        testId="game-note"
      />

      {ply > 0 ? (
        <NoteEditor
          key={ply}
          label={`Note on ${moveLabel(ply)}`}
          saved={game.move_notes?.[String(ply)] ?? ""}
          max={2000}
          busy={moveNote.isPending}
          error={moveNote.error}
          onSave={(text) => moveNote.mutate({ ply, text })}
          testId="move-note"
        />
      ) : (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Select a move to add a note to it.
        </p>
      )}
      <p className="text-xs text-slate-600 dark:text-slate-400">
        Notes stay in your session with the game and are included when you download the PGN with analysis.
      </p>
    </section>
  );
}
