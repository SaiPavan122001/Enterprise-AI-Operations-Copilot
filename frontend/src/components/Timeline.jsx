/**
 * Investigation timeline rendered from REAL backend-derived events only
 * (deployment timestamps and log entry timestamps). Never fabricated.
 */

function formatTimestamp(ts) {
  // Show the time portion when the source format includes it.
  if (!ts) return "";
  return ts.replace("T", " ");
}

export default function Timeline({ events }) {
  if (!events || events.length === 0) return null;
  return (
    <ol className="timeline">
      {events.map((event, index) => (
        <li key={index} className={`timeline-item source-${event.source.replace(/[^\w]/g, "")}`}>
          <span className="timeline-marker" aria-hidden="true" />
          <span className="timeline-time">{formatTimestamp(event.timestamp)}</span>
          <span className="timeline-event">{event.event}</span>
          <span className="timeline-source">{event.source}</span>
        </li>
      ))}
    </ol>
  );
}
