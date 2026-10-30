import { useState } from 'react';
import { postLogin } from '../api/client';

export function LoginForm({ onToken }: { onToken: (t: string) => void }) {
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');

  async function submit(password: string) {
    if (!email.includes('@')) {
      setError('Enter a valid email');
      return;
    }
    onToken(await postLogin(email, password));
  }

  return null;
}
