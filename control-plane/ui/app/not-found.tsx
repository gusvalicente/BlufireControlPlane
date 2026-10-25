import Link from "next/link";
import { Empty } from "@/components/Empty";

export default function NotFound() {
  return (
    <main className="signin">
      <div>
        <Empty icon="search_off" text="Page not found." />
        <div className="actions" style={{ justifyContent: "center" }}><Link className="btn tonal" href="/">Back to Fleet</Link></div>
      </div>
    </main>
  );
}
