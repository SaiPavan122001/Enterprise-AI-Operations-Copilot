/**
 * Investigation timeline rendered from REAL backend-derived events only
 * (deployment timestamps and log entry timestamps). Never fabricated.
 */
export default function Timeline({ events }) {
  if (!events || events.length === 0) return null;
  return (
    <ol className="timeline">
      {events.map((event, index) => (
        <li key={index}>
          <span className="timeline-time">{(event.timestamp || "").replace("T", " ")}</span>
          <span className="timeline-event">{event.event}</span>
        </li>
      ))}
    </ol>
  );
}
