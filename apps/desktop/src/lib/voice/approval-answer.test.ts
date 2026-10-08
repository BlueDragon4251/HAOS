import { describe, expect, it } from 'vitest'
import { decideVoiceApproval, matchApprovalAnswer, type PendingCard, voiceApprovalFor } from './approval-answer.ts'

describe('matchApprovalAnswer', () => {
  it('approves on a short yes', () => {
    for (const text of ['yes', 'Yes, go ahead.', 'do it', 'Approve', 'okay', 'OK', 'Yeah, do it please.', 'Hey Hermes, go ahead!', 'sure', 'Allow it', 'Yes yes']) {
      expect(matchApprovalAnswer(text), text).toBe('approve')
    }
  })

  it('denies on a short no', () => {
    for (const text of ['no', 'Cancel.', "Don't", 'don’t do it', 'Stop!', 'No, thanks.', 'Nope', 'Do not do that', 'deny', 'not now', 'No no no']) {
      expect(matchApprovalAnswer(text), text).toBe('deny')
    }
  })

  it('leaves everything else to the conversation', () => {
    for (const text of [
      'yes, but call it Acme',
      'go ahead and rename it',
      'no, put it in Receipts instead',
      'okay cancel',
      'yes no',
      'thanks',
      'please',
      '',
      'what does it say',
      'yes go ahead and also file the receipts in my documents folder please'
    ]) {
      expect(matchApprovalAnswer(text), text).toBeNull()
    }
  })
})

const card = (id: string, sessionId: string, kind = 'approval'): PendingCard => ({ kind, request: { id, params: { session_id: sessionId } } })

describe('decideVoiceApproval', () => {
  it("answers the oldest card waiting on the voice conversation's session, once or deny", () => {
    const pending = [card('mission-1', 'mission'), card('clarify-1', 'voice', 'clarify'), card('files-1', 'voice'), card('files-2', 'voice')]
    expect(voiceApprovalFor(pending, 'voice')?.request.id).toBe('files-1')
    expect(decideVoiceApproval(pending, 'voice', 'Yes, go ahead.')).toEqual({ requestId: 'files-1', answer: 'approve', choice: 'once' })
    expect(decideVoiceApproval(pending, 'voice', 'no')).toEqual({ requestId: 'files-1', answer: 'deny', choice: 'deny' })
  })

  it('never touches cards from other sessions, other kinds of question, or words that are no answer', () => {
    expect(decideVoiceApproval([card('mission-1', 'mission')], 'voice', 'yes')).toBeNull()
    expect(decideVoiceApproval([card('clarify-1', 'voice', 'clarify')], 'voice', 'yes')).toBeNull()
    expect(decideVoiceApproval([card('files-1', 'voice')], null, 'yes')).toBeNull()
    expect(decideVoiceApproval([card('files-1', 'voice')], 'voice', 'rename it to Acme')).toBeNull()
    expect(voiceApprovalFor([{ kind: 'approval', request: { id: 'gw', params: { gateway_session_id: 'voice' } } }], 'voice')?.request.id).toBe('gw')
  })
})
