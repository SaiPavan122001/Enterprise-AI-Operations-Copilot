import { useState } from "react";
import { login } from "../services/api";
import { MoonIcon, SunIcon } from "./Icons";

/** Sign-in form. The session is an HttpOnly cookie set by the backend; nothing
 * secret is stored in the browser by this component. */
export default function Login({ onSignedIn, theme, onToggleTheme }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const identity = await login(username.trim(), password);
      setPassword("");
      onSignedIn(identity);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-screen">
      <button className="icon-btn login-theme" onClick={onToggleTheme}
        aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}>
        {theme === "dark" ? <SunIcon /> : <MoonIcon />}
      </button>
      <form className="login" onSubmit={submit}>
        <div className="login-mark" aria-hidden="true">O</div>
        <h1>Welcome back</h1>
        <p className="muted">Sign in to Ops Copilot</p>
        <input placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)}
          autoComplete="username" required maxLength={64} aria-label="Username" autoFocus />
        <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password" required maxLength={256} aria-label="Password" />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-btn" type="submit" disabled={busy}>{busy ? "Signing in…" : "Continue"}</button>
        <p className="muted small">Accounts are created by an administrator.</p>
      </form>
    </div>
  );
}
