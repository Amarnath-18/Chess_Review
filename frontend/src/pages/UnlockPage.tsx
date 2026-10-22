import { useState } from "react";
import { useUnlock } from "../api/hooks";
import { Card } from "../components/Card";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/** Shown on a private server until this browser enters the invite code it was given. */
export default function UnlockPage({ revoked = false }: { revoked?: boolean }) {
  useDocumentTitle("Enter your invite code");
  const [code, setCode] = useState("");
  const unlock = useUnlock();

  return (
    <div className="mx-auto max-w-md px-4 py-8">
      <h1 className="mb-3 text-xl font-bold">Enter your invite code</h1>
      <Card>
        <p className="mb-3 text-sm text-slate-600 dark:text-slate-400">
          This is a private server. Whoever runs it gave you a code; enter it once on each browser you use.
          {revoked && " The code this browser used no longer works, so ask for a new one."}
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (code.trim()) unlock.mutate(code.trim());
          }}
        >
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Invite code</span>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              aria-invalid={unlock.isError}
              aria-describedby={unlock.isError ? "unlock-problem" : undefined}
              className="w-full rounded border border-slate-300 bg-white p-2 font-mono text-sm dark:border-slate-600 dark:bg-slate-950"
            />
          </label>
          <button
            type="submit"
            disabled={!code.trim() || unlock.isPending}
            className="mt-3 min-h-11 rounded bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {unlock.isPending ? "Checking…" : "Continue"}
          </button>
          {unlock.isError && (
            <p id="unlock-problem" role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">
              {(unlock.error as Error).message}
            </p>
          )}
        </form>
      </Card>
    </div>
  );
}
