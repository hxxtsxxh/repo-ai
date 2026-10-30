import axios from 'axios';

export const http = axios.create({ baseURL: '/api' });

export async function postLogin(email: string, password: string): Promise<string> {
  const res = await http.post('/login', { email, password });
  return res.data.token;
}
