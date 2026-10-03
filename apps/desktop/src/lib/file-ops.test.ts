import { describe, expect, it } from 'vitest'
import { systemFilesOutputs } from './file-ops.ts'

describe('systemFilesOutputs', () => {
  it('keeps where a moved file lands, not the place it left', () => {
    expect(systemFilesOutputs({ action: 'move', path: '/home/a/Downloads/notes.txt', to: '/home/a/Documents' })).toEqual(['/home/a/Documents/notes.txt'])
    expect(systemFilesOutputs({ action: 'move', path: '~/Downloads/notes.txt', to: '~/Documents/' })).toEqual(['~/Documents/notes.txt'])
  })

  it('takes a destination with a file name as the new path', () => {
    expect(systemFilesOutputs({ action: 'move', path: '~/notes.txt', to: '~/Documents/ideas.txt' })).toEqual(['~/Documents/ideas.txt'])
    expect(systemFilesOutputs({ action: 'copy', path: '~/report.pdf', to: '~/Backup' })).toEqual(['~/Backup/report.pdf'])
  })

  it('leaves nothing behind for trashed items', () => {
    expect(systemFilesOutputs({ action: 'trash', paths: ['~/old.log'] })).toEqual([])
  })

  it('reads every operation of a batch', () => {
    const args = {
      action: 'batch',
      operations: [
        { op: 'mkdir', path: '~/Archive' },
        { op: 'move', path: '~/Desktop/scan.pdf', to: '~/Archive' },
        { op: 'trash', path: '~/Desktop/scan-copy.pdf' }
      ]
    }

    expect(systemFilesOutputs(args)).toEqual(['~/Archive', '~/Archive/scan.pdf'])
  })
})
