import { expect, it } from 'vitest';
import { ValidProfile, Profile } from './contracts';
it('validates the shared note limit in UTF-8 bytes, including Japanese input', () => {
  const scenario = { id: '1', name: 'Scenario', port: 16834, enabled: true, note: 'あ'.repeat(40) };
  const profile = { source: 0, file: '', scenarios: [scenario] };
  expect(ValidProfile.safeParse(profile).success).toBe(true);
  expect(ValidProfile.safeParse({ ...profile, scenarios: [{ ...scenario, note: 'あ'.repeat(41) }] }).success).toBe(false);
  expect(Profile.safeParse({ ...profile, scenarios: [] }).success).toBe(true);
});
