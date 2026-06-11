"use client";

import Link from "next/link";

interface BrandingData {
  id: string;
  name: string;
  primary_color: string;
  logo: string;
  assistant_name: string;
}

export default function ClientShell({ branding }: { branding: BrandingData }) {
  return (
    <div
      className="min-h-screen flex flex-col"
      style={
        {
          "--brand-color": branding.primary_color,
        } as React.CSSProperties
      }
    >
      {/* Header */}
      <header
        className="flex items-center justify-between px-6 py-4 text-white shadow-md"
        style={{ backgroundColor: branding.primary_color }}
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-white/20 rounded-full flex items-center justify-center text-white font-bold text-sm">
            {branding.name.charAt(0)}
          </div>
          <div>
            <div className="font-semibold text-lg">{branding.assistant_name}</div>
            <div className="text-xs text-white/70">{branding.name}</div>
          </div>
        </div>
        <Link
          href="/"
          className="text-white/80 hover:text-white text-sm transition-colors"
        >
          ← Switch client
        </Link>
      </header>

      {/* Chat area (placeholder) */}
      <main className="flex-1 flex flex-col items-center justify-center bg-gray-50 p-8">
        <div className="max-w-2xl w-full">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8 text-center">
            <div
              className="w-16 h-16 rounded-full flex items-center justify-center text-white text-2xl font-bold mx-auto mb-4"
              style={{ backgroundColor: branding.primary_color }}
            >
              {branding.assistant_name.charAt(0)}
            </div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">
              {branding.assistant_name}
            </h2>
            <p className="text-gray-500 mb-6">
              Your AI assistant for {branding.name}. Ask me anything about our documentation.
            </p>
            <div className="flex items-center gap-3 bg-gray-50 rounded-lg p-3 border border-gray-200">
              <input
                type="text"
                placeholder={`Ask ${branding.assistant_name} a question…`}
                className="flex-1 bg-transparent outline-none text-gray-700 placeholder-gray-400 text-sm"
                disabled
              />
              <button
                className="px-4 py-1.5 rounded-md text-white text-sm font-medium transition-opacity opacity-60 cursor-not-allowed"
                style={{ backgroundColor: branding.primary_color }}
                disabled
              >
                Send
              </button>
            </div>
            <p className="text-xs text-gray-400 mt-3">
              Chat functionality coming soon — retrieval pipeline in progress
            </p>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="px-6 py-3 bg-white border-t border-gray-100 text-center">
        <span className="text-xs text-gray-400">
          Powered by{" "}
          <span className="font-medium" style={{ color: branding.primary_color }}>
            Configent
          </span>
        </span>
      </footer>
    </div>
  );
}
