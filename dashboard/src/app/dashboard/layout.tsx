import SessionProvider from "@/components/SessionProvider";
import Sidebar from "@/components/Sidebar";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <div className="flex min-h-screen">
        <Sidebar />
        <main className="flex-1 p-6 overflow-auto">{children}</main>
      </div>
    </SessionProvider>
  );
}
