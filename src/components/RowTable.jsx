import { useEffect, useState } from 'react'

const PAGE = 50

export default function RowTable({ columns, rows, indices, highlight, dropped, droppedColumns }) {
  const [page, setPage] = useState(0)
  useEffect(() => setPage(0), [indices])

  if (!indices.length) return null

  const pages = Math.ceil(indices.length / PAGE)
  const slice = indices.slice(page * PAGE, page * PAGE + PAGE)

  return (
    <div>
      <div className="table-scroll">
        <table className="rows mono">
          <thead>
            <tr>
              <th className="row-number">row</th>
              {columns.map((name) => (
                <th
                  key={name}
                  data-highlight={name === highlight}
                  data-dropped={droppedColumns?.has(name)}
                >
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slice.map((index) => (
              <tr key={index} data-dropped={dropped.has(index)}>
                <td className="row-number">{index}</td>
                {rows[index].map((value, col) => (
                  <td
                    key={col}
                    data-highlight={columns[col] === highlight}
                    data-dropped={droppedColumns?.has(columns[col])}
                  >
                    {value === '' ? <span className="blank">empty</span> : value}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="pager">
          <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>
            previous
          </button>
          <span className="label">
            {page * PAGE + 1} to {Math.min((page + 1) * PAGE, indices.length)} of{' '}
            {indices.length.toLocaleString()}
          </span>
          <button onClick={() => setPage((p) => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1}>
            next
          </button>
        </div>
      )}
    </div>
  )
}
