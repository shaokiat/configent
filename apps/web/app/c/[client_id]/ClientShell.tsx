"use client";

import Link from "next/link";

import ChatPanel from "./ChatPanel";

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
      className="h-dvh flex flex-col"
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

      {/* Chat area */}
      <main className="flex-1 flex flex-col min-h-0 bg-gray-50">
        <ChatPanel branding={branding} />
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
