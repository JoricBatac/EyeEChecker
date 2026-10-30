import { t, type Lighting } from '@scanassist/shared';
import { useMutation } from '@tanstack/react-query';
import { File } from 'expo-file-system';
import { Image } from 'expo-image';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { api, useLocale, usePack } from '@/lib/api';
import { deleteFile, useCheck } from '@/lib/check';
import { Button, Card, Chip, ErrorText, H2, Loading, Muted, Row, Screen } from '@/lib/ui';

const MAX_PHOTOS = 3;
const MAX_EDGE = 1600;
const LIGHTING: Lighting[] = ['normal', 'dim', 'flash'];

/** Resize and re-encode on the phone; re-encoding drops EXIF/GPS metadata before upload. */
async function prepare(asset: ImagePicker.ImagePickerAsset): Promise<string> {
  const ctx = ImageManipulator.manipulate(asset.uri);
  if (Math.max(asset.width, asset.height) > MAX_EDGE) {
    ctx.resize(asset.width >= asset.height ? { width: MAX_EDGE } : { height: MAX_EDGE });
  }
  const image = await ctx.renderAsync();
  return (await image.saveAsync({ compress: 0.9, format: SaveFormat.JPEG })).uri;
}

export default function PhotoStep() {
  const router = useRouter();
  const locale = useLocale();
  const { pack } = usePack();
  const { photos, addPhoto, updatePhoto, removePhoto, set } = useCheck();
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const analyze = useMutation({
    mutationFn: () => {
      const form = new FormData();
      photos.forEach((p, i) => {
        // Expo's fetch needs a real Blob; expo-file-system's File is one (the old { uri, name, type } object is rejected).
        form.append('photos', new File(p.uri), `photo-${i}.jpg`);
        form.append('lighting', p.lighting);
      });
      // Questions come after the first result, picked for this photo (see result screen).
      return api.quick(form);
    },
    onSuccess: (result) => {
      set({ result });
      router.push('/check/result');
    },
  });

  if (!pack) return <Loading />;
  const lightingLabel = (l: Lighting) => t(pack.capture_protocol.lighting_labels?.[l], locale) || l;

  async function add(source: 'camera' | 'library') {
    setError(null);
    try {
      const options: ImagePicker.ImagePickerOptions = { mediaTypes: ['images'], quality: 1, exif: false };
      if (source === 'camera') {
        const perm = await ImagePicker.requestCameraPermissionsAsync();
        if (!perm.granted) throw new Error('Camera permission is needed to take a photo.');
      }
      const r =
        source === 'camera'
          ? await ImagePicker.launchCameraAsync(options)
          : await ImagePicker.launchImageLibraryAsync({
              ...options,
              allowsMultipleSelection: true,
              selectionLimit: MAX_PHOTOS - photos.length,
            });
      if (r.canceled) return;
      for (const asset of r.assets.slice(0, MAX_PHOTOS - photos.length)) {
        const uri = await prepare(asset);
        if (source === 'camera') deleteFile(asset.uri); // keep only the stripped copy
        addPhoto({ uri, lighting: 'normal' });
      }
    } catch (e) {
      setError(e);
    }
  }

  return (
    <Screen>
      <H2>{photos.length > 1 ? `Photos (${photos.length} of ${MAX_PHOTOS})` : 'Photo'}</H2>
      <Muted>
        One photo is enough. You can add up to {MAX_PHOTOS} of the same eye (e.g. normal light and flash); they are
        analyzed together into one result.
      </Muted>
      {photos.map((p, i) => (
        <Card key={p.uri}>
          <Image source={{ uri: p.uri }} style={{ width: '100%', aspectRatio: 4 / 3, borderRadius: 8 }} contentFit="cover" />
          <Muted>Lighting (optional)</Muted>
          <Row>
            {LIGHTING.map((l) => (
              <Chip key={l} label={lightingLabel(l)} selected={p.lighting === l} onPress={() => updatePhoto(i, { lighting: l })} />
            ))}
          </Row>
          <Pressable onPress={() => removePhoto(i)}>
            <Muted>Remove photo</Muted>
          </Pressable>
        </Card>
      ))}
      {photos.length < MAX_PHOTOS && (
        <Row>
          <View style={{ flex: 1 }}>
            <Button title={photos.length ? 'Add another photo' : 'Take photo'} onPress={() => add('camera')} />
          </View>
          <View style={{ flex: 1 }}>
            <Button title="Upload" variant="secondary" onPress={() => add('library')} />
          </View>
        </Row>
      )}
      <ErrorText error={error} />

      <Chip
        label={consent ? 'Patient consented to this photo' : 'Tap to confirm patient consent'}
        selected={consent}
        onPress={() => setConsent(!consent)}
      />
      <Muted>Photos are analyzed and not stored; they are deleted from this phone when you start a new check.</Muted>
      <ErrorText error={analyze.error} />
      <Button
        title={analyze.isPending ? 'Analyzing…' : photos.length > 1 ? `Analyze ${photos.length} photos together` : 'Analyze'}
        onPress={() => analyze.mutate()}
        loading={analyze.isPending}
        disabled={!photos.length || !consent}
      />
    </Screen>
  );
}
