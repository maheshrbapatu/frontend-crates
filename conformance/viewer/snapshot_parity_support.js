// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
import { deleteField, getField, setField } from './mappings.js';

export function boundOracleRecord(value, authoredCase) {
  const result = structuredClone(value);
  const stimulus = getField(result, 'stimulus');
  // A source-local reference binds to that source's authored request, even when
  // the published capture is displayed beside a newer checkout request.
  if (getField(stimulus, 'ref') === 'current') {
    deleteField(stimulus, 'ref');
    setField(stimulus, 'inline', structuredClone(getField(authoredCase, 'request')));
  }
  return result;
}
