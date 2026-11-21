import type { Metadata } from "next";

import { CommandCenter } from "@/components/dashboard/command-center";

export const metadata: Metadata = {
  title: { absolute: "Dashboard · PostPilot AI" },
};

export default function DashboardPage() {
  return <CommandCenter />;
}
