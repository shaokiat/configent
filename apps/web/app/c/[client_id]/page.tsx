import { notFound } from "next/navigation";
import ClientShell from "./ClientShell";

interface BrandingData {
  id: string;
  name: string;
  primary_color: string;
  logo: string;
  assistant_name: string;
}

async function getBranding(clientId: string): Promise<BrandingData | null> {
  const apiUrl = process.env.API_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${apiUrl}/api/clients/${clientId}/branding`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function ClientPage({
  params,
}: {
  params: Promise<{ client_id: string }>;
}) {
  const { client_id } = await params;
  const branding = await getBranding(client_id);

  if (!branding) {
    notFound();
  }

  return <ClientShell branding={branding} />;
}
