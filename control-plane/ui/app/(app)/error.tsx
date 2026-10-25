"use client";

import { Icon } from "@/components/Icon";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="page">
      <div className="appbar"><h1 className="title" style={{ fontWeight: 400 }}>Something went wrong</h1></div>
      <div className="content">
        <div className="banner err">
          <Icon n="error" />
          <div>
            <div className="title-s">The platform API did not answer.</div>
            <div>{error.message || "Unknown error"}</div>
          </div>
        </div>
        <div className="actions">
          <button className="btn filled" onClick={reset}><Icon n="refresh" />Try again</button>
        </div>
      </div>
    </div>
  );
}
