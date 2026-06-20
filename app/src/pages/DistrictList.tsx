import { useEffect, useState } from 'react';
import {
  IonContent,
  IonHeader,
  IonItem,
  IonLabel,
  IonList,
  IonNote,
  IonPage,
  IonSpinner,
  IonText,
  IonTitle,
  IonToolbar,
} from '@ionic/react';

import { fetchDistricts, type District } from '../services/swmmApi';

export default function DistrictList() {
  const [districts, setDistricts] = useState<District[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDistricts()
      .then(setDistricts)
      .catch((e) => setError(String(e.message || e)));
  }, []);

  return (
    <IonPage>
      <IonHeader>
        <IonToolbar>
          <IonTitle>서울 침수 시뮬레이터</IonTitle>
        </IonToolbar>
      </IonHeader>
      <IonContent>
        <div style={{ padding: '14px 16px 4px' }}>
          <IonText color="medium">
            <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>
              EPA SWMM 동역학파 엔진(실물)으로 구·동별 강우-유출 침수를 시뮬레이션합니다.
              구를 선택하세요.
            </p>
          </IonText>
        </div>

        {error && (
          <div style={{ padding: 16 }}>
            <IonText color="danger">
              <p>백엔드에 연결할 수 없습니다: {error}</p>
              <p style={{ fontSize: 12 }}>
                Flask 백엔드가 실행 중인지 확인하세요 (backend/app.py).
              </p>
            </IonText>
          </div>
        )}

        {!districts && !error && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
            <IonSpinner />
          </div>
        )}

        {districts && (
          <IonList inset>
            {districts.map((d) => (
              <IonItem key={d.id} routerLink={`/districts/${d.id}`} detail>
                <IonLabel>
                  <h2>
                    {d.name_ko} <span style={{ color: 'var(--app-muted)' }}>· {d.name_en}</span>
                  </h2>
                  <p style={{ whiteSpace: 'normal' }}>{d.blurb}</p>
                </IonLabel>
                <IonNote slot="end">{d.dongs.length} 동</IonNote>
              </IonItem>
            ))}
          </IonList>
        )}
      </IonContent>
    </IonPage>
  );
}
