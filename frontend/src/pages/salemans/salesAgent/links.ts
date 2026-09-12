/** Links inside this app, such as a document in the knowledge vault or a deal. */
export const isAppLink = (url: string): boolean => /^\/salesman\/[\w\-/?=&.]*$/.test(url);

/** Web links. Anything else (javascript:, data:) is never rendered as a link. */
export const isWebLink = (url: string): boolean => /^https?:\/\//i.test(url);
