import { AccountDTO } from "@/lib/api";
import { AccountsPanel } from "@/features/accounts/AccountsPanel";
import { UsagePanel } from "@/features/usage/UsagePanel";

export function DashboardPage({ accounts }: { accounts: AccountDTO[] }) {
  return (
    <div className="relative mx-auto grid min-h-0 w-full max-w-7xl flex-1 grid-rows-[minmax(0,38fr)_minmax(0,62fr)] gap-4 overflow-hidden px-4 py-4">
      <AccountsPanel accounts={accounts} />
      <div className="min-h-0 flex-1 overflow-hidden">
        <UsagePanel />
      </div>
    </div>
  );
}
