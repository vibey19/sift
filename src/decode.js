// Turning an uploaded file into text.
//
// `File.text()` decodes as UTF-8 and cannot be told otherwise. Anything else
// comes back with U+FFFD where the bytes it could not read used to be, and that
// is unrecoverable: the original byte is gone by the time any code here sees the
// string. A UTF-16 export from Excel, which is what "Unicode Text" means in its
// save dialog, arrives as a NUL between every character and parses as one
// column of gibberish. A Latin-1 file loses every accent in it.
//
// So the bytes are read first and the encoding is worked out from them. What
// this cannot fix is a file that was already damaged before it was saved, where
// the mojibake is genuinely in the bytes; parsing.js repairs that afterwards.

const BOMS = [
  [[0xef, 0xbb, 0xbf], 'utf-8'],
  [[0xff, 0xfe], 'utf-16le'],
  [[0xfe, 0xff], 'utf-16be'],
]

// Enough bytes to judge by. A UTF-16 file gives itself away in the first line.
const SAMPLE_BYTES = 4096

function startsWith(bytes, prefix) {
  return prefix.every((byte, i) => bytes[i] === byte)
}

// UTF-16 without a byte order mark still has a NUL beside every character in
// the ASCII range, which is most of a CSV. Which half of each pair is the NUL
// says which way round the bytes are.
function looksUtf16(bytes) {
  const sample = bytes.subarray(0, SAMPLE_BYTES)
  if (sample.length < 4) return null
  let evenNuls = 0
  let oddNuls = 0
  for (let i = 0; i + 1 < sample.length; i += 2) {
    if (sample[i] === 0) evenNuls += 1
    if (sample[i + 1] === 0) oddNuls += 1
  }
  const pairs = Math.floor(sample.length / 2)
  if (oddNuls / pairs > 0.6 && evenNuls / pairs < 0.1) return 'utf-16le'
  if (evenNuls / pairs > 0.6 && oddNuls / pairs < 0.1) return 'utf-16be'
  return null
}

function tryDecode(bytes, encoding) {
  try {
    return new TextDecoder(encoding, { fatal: true }).decode(bytes)
  } catch {
    return null
  }
}

// { text, encoding }. The encoding is reported rather than hidden, because a
// file that had to be guessed at is worth saying out loud.
export function decodeBytes(buffer) {
  const bytes = new Uint8Array(buffer)

  for (const [bom, encoding] of BOMS) {
    if (startsWith(bytes, bom)) {
      const text = tryDecode(bytes.subarray(bom.length), encoding)
      if (text !== null) return { text, encoding }
    }
  }

  const wide = looksUtf16(bytes)
  if (wide) {
    const text = tryDecode(bytes, wide)
    if (text !== null) return { text, encoding: wide }
  }

  // Strict, so that a file which is not UTF-8 fails here rather than quietly
  // losing a character per accent.
  const utf8 = tryDecode(bytes, 'utf-8')
  if (utf8 !== null) return { text: utf8, encoding: 'utf-8' }

  // Windows-1252 is the fallback because it is what a Western export that is
  // not UTF-8 almost always is, and because it maps every byte to something,
  // so this cannot fail and cannot lose a character.
  return { text: new TextDecoder('windows-1252').decode(bytes), encoding: 'windows-1252' }
}

export async function readFile(file) {
  return decodeBytes(await file.arrayBuffer())
}
