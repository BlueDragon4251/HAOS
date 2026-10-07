import { describe, expect, it } from 'vitest'
import { defaultEffect, type LayerEffects } from '../../../../shared/canvas/comp-format.ts'
import { knownEffects, withEffectsFrom } from './layer-effects.ts'

describe('copying layer styles', () => {
  const styled: LayerEffects = { shadow: { ...defaultEffect.shadow(), distance: 8 }, stroke: defaultEffect.stroke() }

  it('copies the effects this version knows, as new records', () => {
    const copied = knownEffects({ ...styled, satin: { size: 3 } } as LayerEffects)!
    expect(Object.keys(copied).sort()).toEqual(['shadow', 'stroke'])
    expect(copied.shadow).toEqual(styled.shadow)
    expect(copied.shadow).not.toBe(styled.shadow)
    expect(knownEffects(undefined)).toBeUndefined()
    expect(knownEffects({})).toBeUndefined()
  })

  it('replaces a layer’s own effects, keeping what other apps wrote', () => {
    const own = { outerGlow: defaultEffect.outerGlow(), satin: { size: 3 } } as LayerEffects
    const pasted = withEffectsFrom(own, knownEffects(styled))!
    expect(Object.keys(pasted).sort()).toEqual(['satin', 'shadow', 'stroke'])
    expect(pasted.shadow?.distance).toBe(8)
    // Pasting nothing clears the known effects.
    expect(withEffectsFrom({ shadow: defaultEffect.shadow() }, undefined)).toBeUndefined()
  })
})
