import { queryLab } from './api';

export async function executeQuery(sql: string) {
  return queryLab.execute(sql);
}

export async function fetchSchema() {
  return queryLab.schema();
}
