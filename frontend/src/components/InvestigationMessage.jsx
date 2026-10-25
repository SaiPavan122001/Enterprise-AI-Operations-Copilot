import RCAReport from "./RCAReport";

export default function InvestigationMessage({ message }) {
  const { role, content, error, investigation, report, notice } = message;

  if (role === "user") {
    return (
      <div className="msg user">
        <div className="user-bubble">{content}</div>
      </div>
    );
  }

  return (
    <div className="msg assistant">
      {error ? (
        <div className="error-text" role="alert">
          <strong>Something went wrong.</strong> {content}
        </div>
      ) : (
        <RCAReport investigation={investigation} report={report} notice={notice} />
      )}
    </div>
  );
}
