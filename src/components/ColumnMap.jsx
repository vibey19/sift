const NONE = '__none__'

export default function ColumnMap({ profile, label, split, onChange, onRun, onReset, busy }) {
  const options = profile.columns.map((c) => ({
    name: c.name,
    type: c.inferred_type,
    unique: c.n_unique,
  }))
  // A label has to be something a classifier could predict. Offering a text or
  // id column here invites a run that can only come back empty.
  const labelOptions = options.filter((c) =>
    ['categorical', 'boolean', 'numeric', 'constant'].includes(c.type),
  )

  return (
    <div className="panel" style={{ padding: 18 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 22, alignItems: 'flex-end' }}>
        <Field
          title="Label column"
          hint="Enables the mislabel and leakage checks."
          value={label}
          onChange={(v) => onChange({ label: v, split })}
          options={labelOptions}
        />
        <Field
          title="Split column"
          hint="Enables the train/test contamination check."
          value={split}
          onChange={(v) => onChange({ label, split: v })}
          options={options.filter((c) => ['categorical', 'boolean', 'constant'].includes(c.type))}
        />
        <div style={{ display: 'flex', gap: 8, marginLeft: 'auto' }}>
          <button onClick={onReset} disabled={busy}>Use a different file</button>
          {/* Wrapped, or React hands the click event in as the first argument. */}
          <button className="button-primary" onClick={() => onRun()} disabled={busy}>
            {busy ? 'Auditing...' : 'Run again'}
          </button>
        </div>
      </div>
      {!label && (
        <p className="label" style={{ marginTop: 14, marginBottom: 0 }}>
          Twenty-six of the twenty-nine checks have already run. Naming a label column adds the
          other three: mislabelled rows, leaked columns and train/test contamination.
        </p>
      )}
    </div>
  )
}

function Field({ title, hint, value, onChange, options }) {
  return (
    <label style={{ display: 'block' }}>
      <span className="label" style={{ display: 'block', marginBottom: 6 }}>{title}</span>
      <select value={value ?? NONE} onChange={(e) => onChange(e.target.value === NONE ? null : e.target.value)}>
        <option value={NONE}>none</option>
        {options.map((c) => (
          <option key={c.name} value={c.name}>
            {c.name} · {c.type}
          </option>
        ))}
      </select>
      <span className="label" style={{ display: 'block', marginTop: 6, textTransform: 'none', letterSpacing: 0 }}>
        {hint}
      </span>
    </label>
  )
}
