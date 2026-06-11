import Link from "next/link";

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center bg-gray-50 p-8">
      <div className="max-w-2xl w-full text-center">
        <h1 className="text-4xl font-bold text-gray-900 mb-4">POC Factory</h1>
        <p className="text-lg text-gray-600 mb-8">
          Config-driven enterprise AI assistant platform. One YAML file and a folder of documents
          spins up a fully branded, client-specific RAG assistant.
        </p>
        <div className="flex gap-4 justify-center">
          <Link
            href="/c/acme-fab"
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium"
          >
            Acme Fab Equipment
          </Link>
          <Link
            href="/c/meridian-insurance"
            className="px-6 py-3 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-colors font-medium"
          >
            Meridian Insurance
          </Link>
        </div>
      </div>
    </main>
  );
}
