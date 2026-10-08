/*
 * Just enough XML for the parts of a SpreadsheetML package ExcelJS leaves out: the attributes of a
 * tag, the elements of one name with their content, and escaping. The parts are machine-written,
 * and the elements read this way never nest inside one of their own name.
 */

const ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" }

export function decodeXml(text: string): string {
  return text.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (whole, entity: string) => {
    if (entity[0] === '#') {
      const code = entity[1] === 'x' || entity[1] === 'X' ? parseInt(entity.slice(2), 16) : parseInt(entity.slice(1), 10)

      return Number.isFinite(code) && code <= 0x10ffff ? String.fromCodePoint(code) : whole
    }

    return ENTITIES[entity.toLowerCase()] ?? whole
  })
}

export const encodeXml = (text: string): string => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

/** A start tag's attributes by their full name (`r:id` keeps its prefix). */
export function attributesOf(tag: string): Record<string, string> {
  const found: Record<string, string> = {}

  for (const match of tag.matchAll(/([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g)) {
    found[match[1]] = decodeXml(match[2] ?? match[3] ?? '')
  }

  return found
}

export interface XmlElement {
  attributes: Record<string, string>
  /** What is between the start and end tags; empty for an empty element. */
  inner: string
  outer: string
}

const patterns = new Map<string, RegExp>()

/** Every `name` element in `xml`, with or without a namespace prefix. */
export function elementsOf(xml: string, name: string): XmlElement[] {
  let pattern = patterns.get(name)

  if (!pattern) {
    pattern = new RegExp(`<((?:[\\w-]+:)?${name.replace(/\./g, '\\.')})((?:\\s[^>]*?)?)(?:/>|>([\\s\\S]*?)</\\1\\s*>)`, 'g')
    patterns.set(name, pattern)
  }

  return [...xml.matchAll(pattern)].map((match) => ({ attributes: attributesOf(match[2] ?? ''), inner: match[3] ?? '', outer: match[0] }))
}

export const firstElement = (xml: string, name: string): XmlElement | undefined => elementsOf(xml, name)[0]

/** The text of an element (its entities decoded), for elements like `<formula1>` and `<xm:f>`. */
export const textOf = (xml: string, name: string): string | undefined => {
  const element = firstElement(xml, name)

  return element ? decodeXml(element.inner.replace(/<[^>]+>/g, '')) : undefined
}
