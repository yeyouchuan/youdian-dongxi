'use dom';

import { useEffect, useRef, useState } from 'react';

import styles from '@/components/health-sticker-dom.module.css';
import type { HealthStickerPresentation } from '@/domain/types';
import type {
  StickerInstance,
  StickerPeelEndDetail,
} from '@/vendor/sticker-forge/sticker-forge';

interface HealthStickerDomProps {
  presentation: HealthStickerPresentation;
  reduceMotion: boolean;
  onReveal: (id: string) => Promise<void>;
  dom?: import('expo/dom').DOMProps;
}

const DESTROY_AFTER_REVEAL_MS = 420;

function stickerArtwork(title: string) {
  const escapedTitle = title
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');

  return `
    <svg xmlns="http://www.w3.org/2000/svg" width="320" height="210" viewBox="0 0 320 210">
      <rect x="18" y="18" width="284" height="174" rx="54" fill="#F7F7FA"/>
      <rect x="42" y="42" width="236" height="126" rx="40" fill="#FFFFFF"/>
      <circle cx="75" cy="70" r="8" fill="#00C7BE"/>
      <circle cx="245" cy="70" r="8" fill="#00C7BE"/>
      <circle cx="75" cy="140" r="8" fill="#00C7BE"/>
      <circle cx="245" cy="140" r="8" fill="#00C7BE"/>
      <text
        x="160"
        y="75"
        text-anchor="middle"
        dominant-baseline="middle"
        fill="#FF2D55"
        font-family="-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="13"
        font-weight="700">健康亮点</text>
      <text
        x="160"
        y="106"
        text-anchor="middle"
        dominant-baseline="middle"
        fill="#1C1C1E"
        font-family="-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="29"
        font-weight="750">${escapedTitle}</text>
      <circle cx="117" cy="137" r="4" fill="#34C759"/>
      <text
        x="165"
        y="138"
        text-anchor="middle"
        dominant-baseline="middle"
        fill="#6E6E73"
        font-family="-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="12"
        font-weight="600">智能坐垫 · 今日达成</text>
    </svg>
  `;
}

export default function HealthStickerDom({
  presentation,
  reduceMotion,
  onReveal,
}: HealthStickerDomProps) {
  const mountRef = useRef<HTMLButtonElement>(null);
  const revealedRef = useRef(false);
  const revealFromKeyboardRef = useRef<() => void>(() => undefined);
  const [revealed, setRevealed] = useState(reduceMotion);
  const [staticMode, setStaticMode] = useState(reduceMotion);
  const [interactiveVisible, setInteractiveVisible] = useState(!reduceMotion);

  useEffect(() => {
    let disposed = false;
    let failed = false;
    let instance: StickerInstance | null = null;
    let destroyTimer: ReturnType<typeof setTimeout> | null = null;
    const mount = mountRef.current;

    if (reduceMotion || !mount) {
      return () => undefined;
    }

    const destroyInstance = () => {
      if (destroyTimer) {
        clearTimeout(destroyTimer);
        destroyTimer = null;
      }
      instance?.destroy();
      instance = null;
    };

    const reveal = () => {
      if (revealedRef.current || disposed) return;
      revealedRef.current = true;
      setRevealed(true);
      void onReveal(presentation.id);
      destroyTimer = setTimeout(() => {
        instance?.destroy();
        instance = null;
        if (!disposed) setInteractiveVisible(false);
      }, DESTROY_AFTER_REVEAL_MS);
    };

    const handlePeelEnd = (event: Event) => {
      const detail = (event as CustomEvent<StickerPeelEndDetail>).detail;
      if (detail && detail.willReset === false) reveal();
    };

    const handleError = () => {
      failed = true;
      destroyInstance();
      if (disposed) return;
      revealedRef.current = true;
      setStaticMode(true);
      setRevealed(true);
      setInteractiveVisible(false);
    };

    revealFromKeyboardRef.current = () => {
      reveal();
      destroyInstance();
      if (!disposed) setInteractiveVisible(false);
    };

    mount.addEventListener('peelend', handlePeelEnd);
    mount.addEventListener('error', handleError);

    void import('@/vendor/sticker-forge/sticker-forge')
      .then(({ createSticker }) =>
        createSticker(mount, {
          source: {
            type: 'svg',
            svg: stickerArtwork(presentation.title),
          },
          outline: {
            width: 16,
            color: '#FFFFFF',
          },
          shadow: {
            color: '#000000',
            opacity: 0.14,
            blur: 18,
            distance: 12,
            angle: 42,
          },
          peel: {
            radius: 0.12,
            stiffness: 0.72,
            grabWidth: 28,
            maxAngle: 3.55,
            release: 'snap',
          },
          back: {
            color: '#F7F7FA',
            gloss: 0.35,
            roughness: 0.65,
          },
          sound: {
            enabled: false,
            volume: 0,
          },
          tilt: -2,
          wind: 0,
          quality: 'medium',
        }),
      )
      .then((created) => {
        if (disposed || failed) {
          created.destroy();
          return;
        }
        instance = created;
        const canvas = mount.querySelector('canvas');
        canvas?.setAttribute('aria-hidden', 'true');
      })
      .catch(handleError);

    return () => {
      disposed = true;
      mount.removeEventListener('peelend', handlePeelEnd);
      mount.removeEventListener('error', handleError);
      revealFromKeyboardRef.current = () => undefined;
      destroyInstance();
    };
  }, [onReveal, presentation.id, presentation.title, reduceMotion]);

  return (
    <main
      className={[
        styles.stage,
        staticMode ? styles.staticMode : '',
        revealed ? styles.revealed : '',
      ]
        .filter(Boolean)
        .join(' ')}>
      <section
        aria-hidden={!revealed && !staticMode}
        aria-live="polite"
        className={styles.evidence}>
        {staticMode ? (
          <div className={styles.staticSticker} aria-hidden="true">
            <span className={styles.staticStickerLabel}>健康亮点</span>
            <span className={styles.staticStickerTitle}>
              {presentation.title}
            </span>
            <span className={styles.pressureDots}>
              <i />
              <i />
              <i />
              <i />
            </span>
          </div>
        ) : null}

        <dl className={styles.metrics}>
          {presentation.metrics.slice(0, 2).map((metric) => (
            <div className={styles.metric} key={metric.label}>
              <dt>
                <i aria-hidden="true" />
                {metric.label}
              </dt>
              <dd>{metric.value}</dd>
            </div>
          ))}
        </dl>
        <p className={styles.reason}>
          <strong>获得依据</strong>
          <span>{presentation.reason}</span>
        </p>
        <p className={styles.advice}>
          <strong>保持建议</strong>
          <span>{presentation.advice}</span>
        </p>
        {presentation.scopeNote ? (
          <p className={styles.scopeNote}>{presentation.scopeNote}</p>
        ) : null}
      </section>

      {interactiveVisible ? (
        <button
          aria-label={`${presentation.title}。拖动贴纸边缘剥开；键盘用户可按回车查看获得依据。`}
          className={styles.stickerMount}
          onClick={(event) => {
            if (event.detail === 0) revealFromKeyboardRef.current();
          }}
          ref={mountRef}
          type="button"
        />
      ) : null}

      {!revealed && !staticMode ? (
        <p aria-hidden="true" className={styles.hint}>
          从边缘拖动，剥开贴纸
        </p>
      ) : null}
    </main>
  );
}
