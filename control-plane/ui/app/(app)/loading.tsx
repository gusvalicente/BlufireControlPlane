export default function Loading() {
  return (
    <div className="page" aria-busy="true" aria-label="Loading">
      <div className="appbar"><div className="skel" style={{ height: 28, width: 180, marginLeft: 12 }} /></div>
      <div className="content">
        <div className="skel" style={{ height: 96 }} />
        <div className="grid2" style={{ marginTop: 12 }}>
          <div className="skel" style={{ height: 76 }} />
          <div className="skel" style={{ height: 76 }} />
        </div>
        <div className="skel" style={{ height: 132, marginTop: 16 }} />
        <div className="skel" style={{ height: 132, marginTop: 8 }} />
      </div>
    </div>
  );
}
