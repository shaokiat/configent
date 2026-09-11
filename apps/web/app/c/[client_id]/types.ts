export interface BrandingData {
  id: string;
  name: string;
  // "graph" or "loop" — which engine serves this client (D5, D10).
  mode: string;
  primary_color: string;
  logo: string;
  assistant_name: string;
  suggested_questions: string[];
  tagline?: string | null;
}
