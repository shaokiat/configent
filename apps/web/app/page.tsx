import Link from "next/link";
import { ThemeToggle } from "./theme";

const clients = [
  {
    id: "acme-fab",
    name: "Acme Fab Equipment",
    assistantName: "AcmeAssist",
    color: "#1B4F8A",
    description:
      "Industrial equipment specs, maintenance schedules, parts pricing, and compliance documentation — all answered in seconds.",
    tags: ["Specs & Manuals", "Pricing Lookup", "Maintenance"],
  },
  {
    id: "meridian-insurance",
    name: "Meridian Insurance",
    assistantName: "MeridianAssist",
    color: "#1A6B3C",
    description:
      "Coverage details, claims procedures, eligibility rules, and policy comparisons — grounded in official documents.",
    tags: ["Coverage", "Claims", "Eligibility"],
  },
];

export default function Home() {
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
      <section className="flex-1 flex flex-col items-center justify-center px-6 py-20 text-center">
        <div className="inline-flex items-center gap-2 bg-indigo-500/10 border border-indigo-500/20 text-indigo-600 dark:text-indigo-400 text-xs font-medium px-3 py-1.5 rounded-full mb-8">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 dark:bg-indigo-400 animate-pulse" />
          Live demo — real documents, real citations
        </div>

        <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-gray-900 dark:text-white mb-4 max-w-2xl leading-tight">
          Enterprise AI assistants,{" "}
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-500 to-violet-500 dark:from-indigo-400 dark:to-violet-400">
            configured not coded
          </span>
        </h1>

        <p className="text-lg text-gray-500 dark:text-white/50 max-w-xl mb-14 leading-relaxed">
          One YAML file and a folder of documents spins up a fully branded,
          client-specific RAG assistant with streaming responses and live citations.
        </p>

        {/* Client cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 w-full max-w-2xl mb-14">
          {clients.map((client) => (
            <Link
              key={client.id}
              href={`/c/${client.id}`}
              className="group relative bg-gray-50 hover:bg-gray-100 dark:bg-white/5 dark:hover:bg-white/[0.08] border border-gray-200 hover:border-gray-300 dark:border-white/10 dark:hover:border-white/20 rounded-2xl p-6 text-left transition-all duration-200 hover:-translate-y-0.5"
            >
              {/* Color accent */}
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center text-white font-bold text-lg mb-4"
                style={{ backgroundColor: client.color }}
              >
                {client.name.charAt(0)}
              </div>

              <div className="mb-1 flex items-center gap-2">
                <span className="font-semibold text-gray-900 dark:text-white text-sm">{client.name}</span>
              </div>
              <div className="text-xs text-gray-400 dark:text-white/40 mb-3">
                Assistant: <span className="text-gray-500 dark:text-white/60">{client.assistantName}</span>
              </div>

              <p className="text-sm text-gray-500 dark:text-white/50 leading-relaxed mb-4">{client.description}</p>

              <div className="flex flex-wrap gap-1.5">
                {client.tags.map((tag) => (
                  <span
                    key={tag}
                    className="text-[11px] px-2 py-0.5 rounded-full border border-gray-200 dark:border-white/10 text-gray-400 dark:text-white/40"
                  >
                    {tag}
                  </span>
                ))}
              </div>

              <div className="mt-5 flex items-center gap-1 text-xs font-medium text-gray-400 dark:text-white/40 group-hover:text-gray-700 dark:group-hover:text-white/70 transition-colors">
                Launch demo
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
          ))}
        </div>

        {/* How it works strip */}
        <div className="grid grid-cols-3 gap-8 max-w-xl text-center">
          {[
            { step: "1", label: "YAML config", sub: "Model, tools, branding" },
            { step: "2", label: "Drop documents", sub: "PDF, DOCX, Markdown" },
            { step: "3", label: "Instant assistant", sub: "Streaming + citations" },
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
