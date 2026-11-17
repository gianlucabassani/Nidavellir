import type { Theme } from "../types";
import { PageHead, Panel } from "../ui";

export function Profile({
  username,
  theme,
  setTheme,
}: {
  username: string;
  theme: Theme;
  setTheme: (theme: Theme) => void;
}) {
  return (
    <>
      <PageHead
        overline="ACCOUNT / OPERATOR"
        title="Profile"
        subtitle="Your current console identity, session, and display preference."
        action={
          <a className="button button-outline" href="/console/settings">
            Platform settings ↗
          </a>
        }
      />
      <div className="shared-grid">
        <Panel
          eyebrow="01 / IDENTITY"
          title="Operator account"
          className="shared-primary"
        >
          <div className="profile-detail">
            <span className="profile-large-avatar">
              {username.slice(0, 2).toUpperCase()}
            </span>
            <div>
              <strong>{username}</strong>
              <small>Operator · active browser session</small>
            </div>
          </div>
          <div className="arena-detail-list">
            <div>
              <span>Authentication</span>
              <strong>Session cookie</strong>
            </div>
            <div>
              <span>Role</span>
              <strong>Operator</strong>
            </div>
            <div>
              <span>Gateway access</span>
              <strong>Bound per arena</strong>
            </div>
          </div>
          <form className="profile-signout" method="post" action="/logout">
            <input
              type="hidden"
              name="csrf_token"
              value={
                document.querySelector<HTMLMetaElement>(
                  'meta[name="csrf-token"]',
                )?.content || ""
              }
            />
            <button className="button button-danger">Sign out</button>
          </form>
        </Panel>
        <Panel eyebrow="02 / PREFERENCE" title="Appearance">
          <p className="shared-copy">
            Choose the Royal Command day or night palette. This preference is
            stored in this browser.
          </p>
          <div className="theme-choice" role="group" aria-label="Console theme">
            <button
              type="button"
              className="button button-outline"
              aria-pressed={theme === "day"}
              onClick={() => setTheme("day")}
            >
              ☼ Day
            </button>
            <button
              type="button"
              className="button button-outline"
              aria-pressed={theme === "night"}
              onClick={() => setTheme("night")}
            >
              ◐ Night
            </button>
          </div>
          <div className="panel-foot">
            <span>
              Keys and research drafts are not stored in browser preferences.
            </span>
          </div>
        </Panel>
        <Panel
          eyebrow="03 / SHORTCUTS"
          title="Connected work"
          className="shared-wide"
        >
          <div className="shared-shortcuts">
            <a href="/console/library/agents">Agent builds and sessions ↗</a>
            <a href="/console/activity?section=audit">Audit activity ↗</a>
            <a href="/console/library/targets">Targets ↗</a>
          </div>
        </Panel>
      </div>
    </>
  );
}
