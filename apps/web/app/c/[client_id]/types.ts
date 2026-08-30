export interface BrandingData {
  id: string;
  name: string;
  // "pipeline" or "loop" — which engine serves this client (D5).
  mode: string;
  primary_color: string;
  logo: string;
  assistant_name: string;
  suggested_questions: string[];
  tagline?: string | null;
}
