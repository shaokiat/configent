"use client";

import Link from "next/link";

import { ThemeToggle } from "../../theme";
import ChatPanel from "./ChatPanel";
import type { BrandingData } from "./types";

export default function ClientShell({ branding }: { branding: BrandingData }) {
  return (
    <div className="h-dvh flex flex-col bg-white dark:bg-gray-950">
      {/* Header */}
      <header className="flex items-center justify-between px-5 py-3 bg-white dark:bg-gray-950 border-b border-gray-200 dark:border-white/10 shrink-0">
        <div className="flex items-center gap-3">
          {/* Brand avatar */}
          <div
            className="w-9 h-9 rounded-xl flex items-center justify-center text-white font-bold text-base shrink-0"
            style={{ backgroundColor: branding.primary_color }}
          >
            {branding.name.charAt(0)}
          </div>
          <div>
            <div className="font-semibold text-gray-900 dark:text-white text-sm leading-tight">
              {branding.assistant_name}
            </div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400" />
              <span className="text-xs text-gray-400 dark:text-white/40">{branding.name}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-1.5 bg-gray-100 dark:bg-white/5 border border-gray-200 dark:border-white/10 rounded-lg px-3 py-1.5 text-xs text-gray-400 dark:text-white/40">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            RAG · Citations on
          </div>
          <ThemeToggle />
          <Link
            href="/"
            className="flex items-center gap-1 text-xs text-gray-400 dark:text-white/40 hover:text-gray-700 dark:hover:text-white/70 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            All clients
          </Link>
        </div>
      </header>

      {/* Chat */}
      <main className="flex-1 flex flex-col min-h-0">
        <ChatPanel branding={branding} />
      </main>
    </div>
  );
}
