import { useState } from 'react';
import { formatRussianPhone, isRussianPhoneComplete } from '@alfa-hack/core-auth';

type PhoneFieldProps = {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  readOnly?: boolean;
};

export default function PhoneField({ id, value, onChange, disabled = false, readOnly = false }: PhoneFieldProps) {
  const [touched, setTouched] = useState(false);
  const complete = isRussianPhoneComplete(value);
  const started = value.replace(/\D/g, '').length > 1;
  const invalid = touched && started && !complete;

  return (
    <>
      <div className={`phone-control${invalid ? ' phone-control--invalid' : ''}`}>
        <span className="phone-country" aria-hidden="true"><span>+7</span></span>
        <input
          id={id}
          name="phone"
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          placeholder="(999) 123-45-67"
          value={value.replace(/^\+7\s?/, '')}
          onChange={(event) => onChange(formatRussianPhone(event.target.value))}
          onBlur={() => setTouched(true)}
          aria-invalid={invalid}
          aria-describedby={`${id}-error`}
          disabled={disabled}
          readOnly={readOnly}
        />
        {complete && <span className="phone-check" aria-label="Номер введён полностью">✓</span>}
      </div>
      <p className="field-error" id={`${id}-error`} aria-live="polite">
        {invalid ? 'Введите номер полностью.' : ''}
      </p>
    </>
  );
}
