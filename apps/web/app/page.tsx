import Link from "next/link";
import { ThemeToggle } from "./theme";

// Clients come from the API registry, not a hardcoded list — a config dropped in
// `config/` appears here on the next request. The previous hardcoded array had already
// drifted: it was missing the support agent this deployment is built around.
interface ClientSummary {
  id: string;
  name: string;
  mode: string;
  branding: {
    assistant_name: string;
    primary_color: string;
    tagline: string | null;
  };
}

// Rendered per request. The client list is live registry state, and the API is not
// reachable during `next build` — prerendering would bake in the empty-state fallback.
export const dynamic = "force-dynamic";

async function getClients(): Promise<ClientSummary[]> {
  const apiUrl = process.env.API_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${apiUrl}/api/clients`);
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

// Copy the registry cannot supply: what each client is for, in the words a visitor
// needs. Keyed by client_id; a client with no entry still renders from its tagline.
const BLURBS: Record<string, { description: string; tags: string[] }> = {
  "gcp-platform-support": {
    description:
      "Answers Cloud Run, GKE and IAM questions from public Google Cloud documentation, with citations. Questions that depend on your own project can't be answered from those documents, so it files a ticket instead.",
    tags: ["Explicit pipeline", "Two-signal guardrail", "Escalation"],
  },
  "configent-support": {
    description:
      "Answers questions about Configent itself from the published documentation — the dogfood tenant.",
    tags: ["Docs Q&A", "Citations"],
  },
  "acme-fab": {
    description:
      "Industrial equipment specs, maintenance schedules, parts pricing, and compliance documentation — all answered in seconds.",
    tags: ["Specs & Manuals", "Pricing Lookup", "Maintenance"],
  },
  "meridian-insurance": {
    description:
      "Coverage details, claims procedures, eligibility rules, and policy comparisons — grounded in official documents.",
    tags: ["Coverage", "Claims", "Eligibility"],
  },
};

function ClientCard({ client, primary }: { client: ClientSummary; primary?: boolean }) {
  const blurb = BLURBS[client.id];
  const description = blurb?.description ?? client.branding.tagline ?? "";
  const tags = blurb?.tags ?? [];

  return (
    <Link
      href={`/c/${client.id}`}
      className={`group relative bg-gray-50 hover:bg-gray-100 dark:bg-white/5 dark:hover:bg-white/[0.08] border rounded-2xl text-left transition-all duration-200 hover:-translate-y-0.5 ${
        primary
          ? "border-gray-300 dark:border-white/20 p-7"
          : "border-gray-200 hover:border-gray-300 dark:border-white/10 dark:hover:border-white/20 p-6"
      }`}
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div
          className={`rounded-xl flex items-center justify-center text-white font-bold ${
            primary ? "w-12 h-12 text-xl" : "w-10 h-10 text-lg"
          }`}
          style={{ backgroundColor: client.branding.primary_color }}
        >
          {client.name.charAt(0)}
        </div>
        {client.mode === "pipeline" && (
          <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-600 dark:text-emerald-400">
            pipeline
          </span>
        )}
      </div>

      <div className="mb-1 flex items-center gap-2">
        <span
          className={`font-semibold text-gray-900 dark:text-white ${primary ? "text-base" : "text-sm"}`}
        >
          {client.name}
        </span>
      </div>
      <div className="text-xs text-gray-400 dark:text-white/40 mb-3">
        Assistant: <span className="text-gray-500 dark:text-white/60">{client.branding.assistant_name}</span>
      </div>

      <p
        className={`text-gray-500 dark:text-white/50 leading-relaxed mb-4 ${
          primary ? "text-sm max-w-xl" : "text-sm"
        }`}
      >
        {description}
      </p>

      <div className="flex flex-wrap gap-1.5">
        {tags.map((tag) => (
          <span
            key={tag}
            className="text-[11px] px-2 py-0.5 rounded-full border border-gray-200 dark:border-white/10 text-gray-400 dark:text-white/40"
          >
            {tag}
          </span>
        ))}
      </div>

      <div className="mt-5 flex items-center gap-1 text-xs font-medium text-gray-400 dark:text-white/40 group-hover:text-gray-700 dark:group-hover:text-white/70 transition-colors">
        {primary ? "Open the support agent" : "Launch demo"}
        <svg
          className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </div>
    </Link>
  );
}

export default async function Home() {
  const clients = await getClients();
  const pipeline = clients.filter((c) => c.mode === "pipeline");
  const loop = clients.filter((c) => c.mode !== "pipeline");

  return (
    <div className="min-h-screen bg-white dark:bg-gray-950 text-gray-900 dark:text-white flex flex-col">
      {/* Nav */}
      <nav className="border-b border-gray-200 dark:border-white/10 px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-md bg-indigo-500 flex items-center justify-center text-white font-bold text-sm">
            C
          </div>
          <span className="font-semibold text-gray-900 dark:text-white tracking-tight">Configent</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400 dark:text-white/40 font-mono">POC · v0.1</span>
          <ThemeToggle />
        </div>
      </nav>

      {/* Hero */}
      <section className="flex-1 flex flex-col items-center px-6 py-20 text-center">
        <div className="inline-flex items-center gap-2 bg-indigo-500/10 border border-indigo-500/20 text-indigo-600 dark:text-indigo-400 text-xs font-medium px-3 py-1.5 rounded-full mb-8">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 dark:bg-indigo-400 animate-pulse" />
          Live demo — real documents, real citations
        </div>

        <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-gray-900 dark:text-white mb-4 max-w-2xl leading-tight">
          A support agent that{" "}
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-500 to-violet-500 dark:from-indigo-400 dark:to-violet-400">
            knows what it can&apos;t answer
          </span>
        </h1>

        <p className="text-lg text-gray-500 dark:text-white/50 max-w-xl mb-14 leading-relaxed">
          It answers from documentation with citations, and escalates to a filed ticket
          when a question depends on something the documentation cannot know. That
          decision is a branch in Python, and every stage of it is on the record.
        </p>

        {clients.length === 0 ? (
          <div className="w-full max-w-2xl mb-14 rounded-2xl border border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-white/5 p-8">
            <p className="text-sm text-gray-500 dark:text-white/50 leading-relaxed">
              No clients loaded — the API isn&apos;t reachable. Start the stack with{" "}
              <code className="font-mono text-gray-700 dark:text-white/70">make dev</code> and reload.
            </p>
          </div>
        ) : (
          <>
            {/* Primary: the pipeline client(s) this deployment is built around */}
            {pipeline.length > 0 && (
              <div className="w-full max-w-2xl mb-10 grid grid-cols-1 gap-5">
                {pipeline.map((client) => (
                  <ClientCard key={client.id} client={client} primary />
                ))}
              </div>
            )}

            {/* Secondary: clients still on the free-form loop. Same codebase, same
                entry point, different engine — selected by one line of config. */}
            {loop.length > 0 && (
              <div className="w-full max-w-2xl mb-14">
                <div className="flex items-center gap-3 mb-5">
                  <div className="h-px flex-1 bg-gray-200 dark:bg-white/10" />
                  <span className="text-xs text-gray-400 dark:text-white/30 uppercase tracking-wide font-medium">
                    Also in this deployment · free-form loop
                  </span>
                  <div className="h-px flex-1 bg-gray-200 dark:bg-white/10" />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                  {loop.map((client) => (
                    <ClientCard key={client.id} client={client} />
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {/* How it works strip */}
        <div className="grid grid-cols-3 gap-8 max-w-xl text-center">
          {[
            { step: "1", label: "YAML config", sub: "Model, tools, thresholds" },
            { step: "2", label: "Drop documents", sub: "Markdown corpus" },
            { step: "3", label: "Instant assistant", sub: "Citations + audit trail" },
          ].map(({ step, label, sub }) => (
            <div key={step} className="flex flex-col items-center gap-1.5">
              <div className="w-7 h-7 rounded-full bg-gray-100 dark:bg-white/5 border border-gray-200 dark:border-white/10 flex items-center justify-center text-gray-400 dark:text-white/40 text-xs font-mono">
                {step}
              </div>
              <span className="text-sm font-medium text-gray-600 dark:text-white/60">{label}</span>
              <span className="text-xs text-gray-400 dark:text-white/30">{sub}</span>
            </div>
          ))}
        </div>
      </section>

      <footer className="border-t border-gray-200 dark:border-white/10 px-8 py-4 text-center">
        <span className="text-xs text-gray-300 dark:text-white/20">
          Built with Next.js · FastAPI · Claude · pgvector
        </span>
      </footer>
    </div>
  );
}
