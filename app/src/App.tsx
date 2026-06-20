import { IonApp, IonRouterOutlet } from '@ionic/react';
import { IonReactRouter } from '@ionic/react-router';
import { Redirect, Route } from 'react-router-dom';

import DistrictList from './pages/DistrictList';
import DistrictDetail from './pages/DistrictDetail';

export default function App() {
  return (
    <IonApp>
      <IonReactRouter>
        <IonRouterOutlet>
          <Route exact path="/districts" component={DistrictList} />
          <Route exact path="/districts/:gu" component={DistrictDetail} />
          <Route exact path="/">
            <Redirect to="/districts" />
          </Route>
        </IonRouterOutlet>
      </IonReactRouter>
    </IonApp>
  );
}
