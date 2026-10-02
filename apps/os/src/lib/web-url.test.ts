import { describe, expect, it } from 'vitest'
import { describeWebUrl, isWebUrl } from './web-url.ts'

describe('isWebUrl', () => {
  it('accepts http(s) pages only', () => {
    expect(isWebUrl('https://portal.nousresearch.com/manage-subscription?user_code=ABCD-1234')).toBe(true)
    expect(isWebUrl('http://127.0.0.1:5180/')).toBe(true)
    expect(isWebUrl('HTTPS://EXAMPLE.COM')).toBe(true)
  })

  it('rejects anything that could reach the machine or the shell', () => {
    expect(isWebUrl('file:///etc/hosts')).toBe(false)
    expect(isWebUrl('javascript:alert(1)')).toBe(false)
    expect(isWebUrl('hermes://settings')).toBe(false)
    expect(isWebUrl('https://')).toBe(false)
    expect(isWebUrl('example.com')).toBe(false)
    expect(isWebUrl('')).toBe(false)
  })
})

describe('describeWebUrl', () => {
  it('splits host from the rest and flags https', () => {
    expect(describeWebUrl('https://portal.nousresearch.com/manage-subscription?user_code=ABCD-1234')).toEqual({
      host: 'portal.nousresearch.com',
      rest: '/manage-subscription?user_code=ABCD-1234',
      secure: true
    })
    expect(describeWebUrl('http://localhost:8080')).toEqual({ host: 'localhost:8080', rest: '', secure: false })
  })

  it('returns null for non-web URLs', () => {
    expect(describeWebUrl('file:///tmp/x.html')).toBeNull()
    expect(describeWebUrl('not a url')).toBeNull()
  })
})
