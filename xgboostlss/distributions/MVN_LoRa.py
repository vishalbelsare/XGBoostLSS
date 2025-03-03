from torch.distributions import LowRankMultivariateNormal as LowRankMultivariateNormal_Torch
from .multivariate_distribution_utils import Multivariate_DistributionClass
from ..utils import *

from typing import Dict, Optional, List, Callable
import numpy as np
import pandas as pd
from itertools import combinations


class MVN_LoRa(Multivariate_DistributionClass):
    """
    Multivariate Normal distribution class.

    Creates a multivariate normal distribution with covariance matrix having a low-rank form parameterized by
    `cov_factor` and `cov_diag`:

        `covariance_matrix = cov_factor @ cov_factor.T + cov_diag`


    Distributional Parameters
    -------------------------
    loc: torch.Tensor
        Mean of the distribution (often referred to as mu).
    cov_factor: torch.Tensor
        Factor part of low-rank form of covariance matrix.
    cov_diag: torch.Tensor
        Diagonal part of low-rank form of covariance matrix.

    Source
    -------------------------
    https://pytorch.org/docs/stable/distributions.html#lowrankmultivariatenormal

    Parameters
    -------------------------
    D: int
        Number of targets.
    rank: int
        Rank of the low-rank form of the covariance matrix.
    stabilization: str
        Stabilization method for the Gradient and Hessian. Options are "None", "MAD", "L2".
    response_fn: str
        Response function for transforming the distributional parameters to the correct support. Options are
        "exp" (exponential) or "softplus" (softplus).
    loss_fn: str
        Loss function. Options are "nll" (negative log-likelihood).
    """
    def __init__(self,
                 D: int,
                 rank: int,
                 stabilization: str = "None",
                 response_fn: str = "exp",
                 loss_fn: str = "nll"
                 ):
        # Specify Response Function
        if response_fn == "exp":
            response_fn = exp_fn
        elif response_fn == "softplus":
            response_fn = softplus_fn
        else:
            raise ValueError("Invalid response function. Please choose from 'exp' or 'softplus'.")

        # Set the parameters specific to the distribution
        distribution = LowRankMultivariateNormal_Torch
        param_dict = MVN_LoRa.create_param_dict(n_targets=D, rank=rank, response_fn=response_fn)
        distribution_arg_names = ["loc", "cov_factor", "cov_diag"]
        torch.distributions.Distribution.set_default_validate_args(False)

        # Specify Distribution Class
        super().__init__(distribution=distribution,
                         univariate=False,
                         distribution_arg_names=distribution_arg_names,
                         n_targets=D,
                         rank=rank,
                         n_dist_param=len(param_dict),
                         param_dict=param_dict,
                         param_transform=MVN_LoRa.param_transform,
                         get_dist_params=MVN_LoRa.get_dist_params,
                         discrete=False,
                         stabilization=stabilization,
                         loss_fn=loss_fn
                         )

    @staticmethod
    def create_param_dict(n_targets: int,
                          rank: int,
                          response_fn: Callable
                          ) -> Dict:
        """ Function that transforms the distributional parameters to the desired scale.

        Arguments
        ---------
        n_targets: int
            Number of targets.
        rank: int
            Rank of the low-rank form of the covariance matrix.
        response_fn: Callable
            Response function.

        Returns
        -------
        param_dict: Dict
            Dictionary of distributional parameters.
        """
        # Location
        param_dict = {"location_" + str(i + 1): identity_fn for i in range(n_targets)}

        # Low Rank Factor
        cov_factor_dict = {"cov_factor_" + str(i + 1): identity_fn for i in range(n_targets * rank)}
        param_dict.update(cov_factor_dict)

        # Low Rank Diagonal
        cov_diag_dict = {"cov_diag_" + str(i + 1): response_fn for i in range(n_targets)}
        param_dict.update(cov_diag_dict)

        return param_dict

    @staticmethod
    def param_transform(params: List[torch.Tensor],
                        param_dict: Dict,
                        n_targets: int,
                        rank: int,
                        n_obs: Optional[int],
                        ) -> List[torch.Tensor]:
        """ Function that returns a list of parameters for a multivariate normal distribution, parameterized
        by a covariance matrix having a low-rank form parameterized by `cov_factor` and `cov_diag`:

        `covariance_matrix = cov_factor @ cov_factor.T + cov_diag`

        Arguments
        ---------
        params: List[torch.Tensor]
            List of distributional parameters.
        param_dict: Dict
        n_targets: int
            Number of targets.
        rank: int
            Rank of the low-rank form of the covariance matrix.
        n_obs: Optional[int],
            Number of observations.

        Returns
        -------
        params: List[torch.Tensor]
            List of parameters.
        """
        # Transform Parameters to respective scale
        n_params = len(params)
        params = [
            response_fun(params[i].reshape(-1, 1)) for i, (dist_param, response_fun) in enumerate(param_dict.items())
        ]

        # Location
        loc = torch.cat(params[:n_targets], axis=1)

        # Low Rank Factor
        cov_factor = torch.cat(
            params[n_targets:(n_params - n_targets)], axis=1
        ).reshape(-1, n_targets, rank)

        # Low Rank Diagonal
        cov_diag = torch.cat(params[-n_targets:], axis=1)

        params = [loc, cov_factor, cov_diag]

        return params

    @staticmethod
    def get_dist_params(n_targets: int,
                        dist_pred: torch.distributions.Distribution,
                        ) -> pd.DataFrame:
        """
        Function that returns the predicted distributional parameters.

        Arguments
        ---------
        n_targets: int
            Number of targets.
        dist_pred: torch.distributions.Distribution
            Predicted distribution.

        Returns
        -------
        dist_params_df: pd.DataFrame
            DataFrame with predicted distributional parameters.
        """

        # Location
        location_df = pd.DataFrame(dist_pred.loc.numpy())
        location_df.columns = [f"location_{i + 1}" for i in range(n_targets)]

        # Sigma
        scale_df = pd.DataFrame(dist_pred.stddev.detach().numpy())
        scale_df.columns = [f"scale_{i + 1}" for i in range(n_targets)]

        # Rho
        n_obs = location_df.shape[0]
        n_rho = int((n_targets * (n_targets - 1)) / 2)
        cov_mat = dist_pred.covariance_matrix
        rho_df = pd.DataFrame(
            np.concatenate(
                [MVN_LoRa.covariance_to_correlation(cov_mat[i]).reshape(-1, n_rho) for i in range(n_obs)],
                axis=0)
        )
        rho_idx = list(combinations(range(1, n_targets + 1), 2))
        rho_df.columns = [f"rho_{''.join(map(str, rho_idx[i]))}" for i in range(n_targets)]

        # Concatenate
        dist_params_df = pd.concat([location_df, scale_df, rho_df], axis=1)

        return dist_params_df

    @staticmethod
    def covariance_to_correlation(cov_mat: torch.Tensor) -> np.ndarray:
        """ Function that calculates the correlation matrix from the covariance matrix.

        Arguments
        ---------
        cov_mat: torch.Tensor
            Covariance matrix.

        Returns
        -------
        cor_mat: np.ndarray
            Correlation matrix.
        """
        cov_mat = np.array(cov_mat)
        diag = np.sqrt(np.diag(np.diag(cov_mat)))
        diag_inv = np.linalg.inv(diag)
        cor_mat = diag_inv @ cov_mat @ diag_inv
        cor_mat = cor_mat[np.tril_indices_from(cor_mat, k=-1)]

        return cor_mat
