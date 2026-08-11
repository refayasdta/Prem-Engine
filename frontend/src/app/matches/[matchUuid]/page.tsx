import { ProductShell } from "@/components/product-shell";
import { OfficialMatch } from "./official-match";

export default async function MatchPage({
  params,
}: {
  params: Promise<{ matchUuid: string }>;
}) {
  const { matchUuid } = await params;
  return (
    <ProductShell active={null}>
      <OfficialMatch matchUuid={matchUuid} />
    </ProductShell>
  );
}
