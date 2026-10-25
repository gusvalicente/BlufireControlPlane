import Link from "next/link";
import { Empty } from "@/components/Empty";

export default function NotFound() {
  return (
    <div className="page">
      <div className="content">
        <Empty icon="search_off" text="That item does not exist or was removed." />
        <div className="actions" style={{ justifyContent: "center" }}><Link className="btn tonal" href="/">Back to Fleet</Link></div>
      </div>
    </div>
  );
}
