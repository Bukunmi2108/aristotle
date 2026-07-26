const CONVERSATION_PATH_PATTERN =
  /^\/c\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

export type AppRoute =
  | { type: "new" }
  | { type: "conversation"; conversationId: string }
  | { type: "invalid" };

export function routeFromPath(pathname: string): AppRoute {
  if (pathname === "/") {
    return { type: "new" };
  }

  const match = CONVERSATION_PATH_PATTERN.exec(pathname);
  if (match) {
    return { type: "conversation", conversationId: match[1] };
  }

  return { type: "invalid" };
}

export function pathForConversation(id: string): string {
  return `/c/${id}`;
}

export function artifactIdFromLocation(location: string): string | null {
  const query = location.includes("?") ? location.slice(location.indexOf("?")) : location;
  return new URLSearchParams(query).get("artifact");
}

export function urlForArtifact(
  conversationId: string,
  artifactId: string | null,
  currentSearch = "",
): string {
  const params = new URLSearchParams(currentSearch);
  if (artifactId) {
    params.set("artifact", artifactId);
  } else {
    params.delete("artifact");
  }
  const query = params.toString();
  return `${pathForConversation(conversationId)}${query ? `?${query}` : ""}`;
}
