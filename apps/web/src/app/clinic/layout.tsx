import { Shell } from "@/components/Shell";

export default function ClinicLayout({ children }: LayoutProps<"/clinic">) {
  return <Shell area="clinic">{children}</Shell>;
}
