export type Profile = { id: string; name: string; bio: string };

export async function fetchProfile(userId: string, signal?: AbortSignal): Promise<Profile> {
  const response = await fetch(`/api/users/${encodeURIComponent(userId)}/profile`, { signal });
  if (!response.ok) {
    throw new Error(`profile request failed: ${response.status}`);
  }
  return (await response.json()) as Profile;
}
