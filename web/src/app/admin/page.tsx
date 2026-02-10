"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { AdminPanel } from "@/components/AdminPanel";

export default function AdminPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  const isAdmin = user?.is_admin ?? false;

  useEffect(() => {
    if (loading) return;

    if (!user) {
      // Not logged in — redirect to home
      router.push("/");
      return;
    }
  }, [user, loading, router]);

  if (loading) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8">
        <div className="terminal-card p-8 text-center">
          <span className="text-[var(--muted)]">loading...</span>
        </div>
      </main>
    );
  }

  if (!user || !isAdmin) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8">
        <div className="terminal-card p-8 text-center">
          <h1 className="mb-4 text-xl text-[var(--danger)]">Access Denied</h1>
          <p className="text-[var(--muted)]">
            {!user
              ? "You must be logged in to access the admin panel."
              : "You don't have admin permissions."}
          </p>
          <button
            onClick={() => router.push("/")}
            className="terminal-btn mt-4"
          >
            Go Home
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-medium text-[var(--foreground)]">
          <span className="text-[var(--primary)]">$</span> admin
        </h1>
        <button
          onClick={() => router.push("/")}
          className="text-sm text-[var(--muted)] hover:text-[var(--foreground)]"
        >
          &larr; back to feed
        </button>
      </div>

      <AdminPanel defaultExpanded />
    </main>
  );
}
