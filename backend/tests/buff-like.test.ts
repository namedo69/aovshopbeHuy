import { describe, it, expect } from 'vitest';
import { buffLikeInput } from '../src/modules/buff-like.js';

describe('buff like checkout snapshot', () => {
  it('uses server product quota, not customer requested likes', () => {
    expect(buffLikeInput({ likesPerItem: 100 }, { targetName: '  Hero  ', requested: 999999 }, 3))
      .toEqual({ productType: 'buff_like', targetName: 'Hero', requested: 300 });
  });
  it('rejects empty names, invalid packages and overflow', () => {
    expect(() => buffLikeInput({ likesPerItem: 100 }, { targetName: ' ' }, 1)).toThrow();
    expect(() => buffLikeInput({ likesPerItem: 0 }, { targetName: 'Hero' }, 1)).toThrow();
    expect(() => buffLikeInput({ likesPerItem: 1000000 }, { targetName: 'Hero' }, 2)).toThrow();
  });
});
