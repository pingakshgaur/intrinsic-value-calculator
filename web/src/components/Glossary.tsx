import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { GLOSSARY } from "../lib/glossary";
import { Icon } from "./ui";

/** The glossary drawer's body: search, topic chips, and the terms grouped under each topic. */
export function Glossary({ onNavigate }: { onNavigate: () => void }) {
  const [find, setFind] = useState("");
  const [topic, setTopic] = useState<string | null>(null);
  const body = useRef<HTMLDivElement>(null);
  const f = find.trim().toLowerCase();
  const topics = useMemo(() => GLOSSARY
    .filter((t) => !topic || t.id === topic)
    .map((t) => ({ ...t, terms: t.terms.filter((x) => !f || `${x.term} ${x.sym ?? ""} ${x.text}`.toLowerCase().includes(f)) }))
    .filter((t) => t.terms.length), [f, topic]);
  const count = topics.reduce((n, t) => n + t.terms.length, 0);
  const pick = (id: string | null) => { setTopic(id); body.current?.closest(".drawer-b")?.scrollTo({ top: 0 }); };

  return (
    <div className="gl">
      <div className="gl-top">
        <div className="search"><Icon name="search" /><input autoFocus value={find} onChange={(e) => setFind(e.target.value)} placeholder="Search terms, symbols or meanings" />{find && <button className="ibtn xs" onClick={() => setFind("")} title="Clear"><Icon name="close" className="xs" /></button>}</div>
        <div className="gl-chips">
          <button className={!topic ? "on" : ""} onClick={() => pick(null)}>All</button>
          {GLOSSARY.map((t) => <button key={t.id} className={topic === t.id ? "on" : ""} onClick={() => pick(topic === t.id ? null : t.id)}><Icon name={t.icon} className="xs" />{t.title}</button>)}
        </div>
      </div>
      <div className="gl-body" ref={body}>
        {!count && <div className="muted small" style={{ padding: "24px 0", textAlign: "center" }}>No term matches “{find}”.</div>}
        {topics.map((t) => (
          <section key={t.id} className="gl-topic">
            <h3><Icon name={t.icon} className="sm" />{t.title}<span className="n">{t.terms.length}</span></h3>
            <p className="xs faint gl-blurb">{t.blurb}</p>
            <dl>
              {t.terms.map((x) => (
                <div key={x.term} className="gl-term">
                  <dt>
                    <span className="strong">{x.term}</span>
                    {x.sym && x.sym !== x.term && <code>{x.sym}</code>}
                    {x.where && <Link to={x.where} className="gl-where" onClick={onNavigate} title="Open the page">open<Icon name="arrow-right" className="xs" /></Link>}
                  </dt>
                  <dd className="muted small">{x.text}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
        <div className="xs faint" style={{ paddingTop: 6 }}><kbd>Ctrl K</kbd> search · <kbd>Alt 1–9</kbd> pages · <kbd>Ctrl \</kbd> sidebar · <kbd>?</kbd> glossary · <kbd>↑ ↓</kbd> rows in grids</div>
      </div>
    </div>
  );
}
