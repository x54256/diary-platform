import assert from 'node:assert/strict'
import test from 'node:test'

import { orderAudioFiles } from '../utils/audio-file-order.ts'

test('orders selected audio files by last modified time and then filename', () => {
  const files = [
    { name: '3.m4a', lastModified: 30 },
    { name: '2.m4a', lastModified: 20 },
    { name: '1.m4a', lastModified: 20 },
  ]

  assert.deepEqual(orderAudioFiles(files).map(file => file.name), ['1.m4a', '2.m4a', '3.m4a'])
})
