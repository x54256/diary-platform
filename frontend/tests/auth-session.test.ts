import assert from 'node:assert/strict'
import test from 'node:test'

import { getLoginPath, getSafeRedirect, getTokenExpiresAt, isTokenExpired } from '../utils/auth-session.ts'

const tokenWithExpiration = (expiration: number) => {
  const payload = Buffer.from(JSON.stringify({ exp: expiration })).toString('base64url')
  return `header.${payload}.signature`
}

test('expired or malformed tokens are rejected locally', () => {
  assert.equal(getTokenExpiresAt(tokenWithExpiration(100)), 100_000)
  assert.equal(getTokenExpiresAt('invalid-token'), null)
  assert.equal(isTokenExpired(tokenWithExpiration(100), 101_000), true)
  assert.equal(isTokenExpired(tokenWithExpiration(100), 99_000), false)
  assert.equal(isTokenExpired('invalid-token', 99_000), true)
})

test('login redirects preserve only internal application paths', () => {
  assert.equal(getLoginPath('/diary/123?tab=analysis'), '/login?redirect=%2Fdiary%2F123%3Ftab%3Danalysis')
  assert.equal(getSafeRedirect('/diary/123?tab=analysis'), '/diary/123?tab=analysis')
  assert.equal(getSafeRedirect('https://attacker.example'), '/')
  assert.equal(getSafeRedirect('//attacker.example'), '/')
})
