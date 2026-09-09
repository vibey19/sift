import assert from 'node:assert/strict'
import { test } from 'node:test'

import { columnIndex, detectDelimiter, parseCsv, toCsv } from './csv.js'

test('parses a plain file', () => {
  const { columns, rows } = parseCsv('a,b\n1,2\n3,4\n')
  assert.deepEqual(columns, ['a', 'b'])
  assert.deepEqual(rows, [['1', '2'], ['3', '4']])
})

test('a trailing newline does not become an empty row', () => {
  assert.equal(parseCsv('a,b\n1,2\n').rows.length, 1)
  assert.equal(parseCsv('a,b\n1,2').rows.length, 1)
})

test('keeps commas inside quoted fields', () => {
  const { rows } = parseCsv('a,b\n"Smith, John",42\n')
  assert.deepEqual(rows[0], ['Smith, John', '42'])
})

test('keeps newlines inside quoted fields', () => {
  const { rows } = parseCsv('a,b\n"line one\nline two",42\n')
  assert.deepEqual(rows[0], ['line one\nline two', '42'])
  assert.equal(rows.length, 1)
})

test('doubled quotes are one literal quote', () => {
  const { rows } = parseCsv('a\n"she said ""hello"""\n')
  assert.deepEqual(rows[0], ['she said "hello"'])
})

test('handles CRLF and a lone CR', () => {
  assert.deepEqual(parseCsv('a,b\r\n1,2\r\n').rows, [['1', '2']])
  assert.deepEqual(parseCsv('a,b\r1,2\r').rows, [['1', '2']])
})

test('empty fields survive', () => {
  assert.deepEqual(parseCsv('a,b,c\n1,,3\n').rows[0], ['1', '', '3'])
  assert.deepEqual(parseCsv('a,b\n,\n').rows[0], ['', ''])
})

test('a quoted empty string is preserved', () => {
  assert.deepEqual(parseCsv('a,b\n"",x\n').rows[0], ['', 'x'])
})

test('ragged rows are padded and over-long rows truncated', () => {
  const { rows } = parseCsv('a,b,c\n1,2\n1,2,3,4\n')
  assert.deepEqual(rows[0], ['1', '2', ''])
  assert.deepEqual(rows[1], ['1', '2', '3'])
})

test('detects tabs and semicolons', () => {
  assert.equal(detectDelimiter('a\tb\tc\n'), '\t')
  assert.equal(detectDelimiter('a;b;c\n'), ';')
  assert.equal(detectDelimiter('a,b,c\n'), ',')
  assert.deepEqual(parseCsv('a\tb\n1\t2\n').columns, ['a', 'b'])
})

test('a comma inside a quoted header does not outvote a tab file', () => {
  assert.equal(detectDelimiter('"a,b"\tc\n1\t2\n'), '\t')
})

test('strips a byte order mark from the first column name', () => {
  const { columns } = parseCsv('﻿id,name\n1,x\n')
  assert.deepEqual(columns, ['id', 'name'])
})

test('unnamed columns get a positional name', () => {
  assert.deepEqual(parseCsv('a,,c\n1,2,3\n').columns, ['a', 'column_2', 'c'])
})

test('round trips through toCsv', () => {
  const original = 'a,b\n"Smith, John","said ""hi"""\n"two\nlines",4\n'
  const { columns, rows } = parseCsv(original)
  const again = parseCsv(toCsv(columns, rows))
  assert.deepEqual(again.columns, columns)
  assert.deepEqual(again.rows, rows)
})

test('columnIndex maps names to positions', () => {
  assert.deepEqual(columnIndex(['a', 'b']), { a: 0, b: 1 })
})

test('an empty file does not throw', () => {
  assert.deepEqual(parseCsv(''), { columns: [], rows: [], delimiter: ',' })
})
